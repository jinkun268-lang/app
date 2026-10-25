param(
    [Parameter(Mandatory = $true)][string]$NginxExe,
    [ValidateSet('Start', 'Test', 'Reload', 'Stop')][string]$Action = 'Start',
    [int]$Port = 8080,
    [int]$ApiPort = 8000,
    [string]$RuntimeDir,
    [string]$FrontendDir
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$nginx = (Resolve-Path -LiteralPath $NginxExe).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $projectRoot '.runtime/gateway' }
if (-not $FrontendDir) { $FrontendDir = Join-Path $projectRoot 'admin/dist' }
$runtime = [IO.Path]::GetFullPath($RuntimeDir)
$prefix = $runtime.Replace('\', '/').TrimEnd('/') + '/'
$config = Join-Path $runtime 'nginx.conf'
$pidFile = Join-Path $runtime 'logs/nginx.pid'
$startupTimeoutSeconds = 10
$stopTimeoutSeconds = 15

function Read-PidFile {
    # Polling helper: a locked or partially written pid file reads as empty.
    if (-not (Test-Path -LiteralPath $pidFile)) { return '' }
    try { return [IO.File]::ReadAllText($pidFile).Trim() } catch { return '' }
}

function Split-CommandLine([string]$CommandLine) {
    # Quote-aware tokenizer; Windows keeps quotes in Win32_Process.CommandLine.
    $tokens = @()
    $current = ''
    $quoted = $false
    foreach ($char in $CommandLine.ToCharArray()) {
        if ($char -eq '"') { $quoted = -not $quoted; continue }
        if (-not $quoted -and [char]::IsWhiteSpace($char)) {
            if ($current) { $tokens += $current; $current = '' }
            continue
        }
        $current += $char
    }
    if ($current) { $tokens += $current }
    return $tokens
}

function Get-CommandLineArgument($Tokens, [string]$Name) {
    for ($i = 0; $i -lt $Tokens.Count - 1; $i++) {
        if ($Tokens[$i] -ieq $Name) { return $Tokens[$i + 1] }
    }
    return $null
}

function Assert-GatewayMaster([int]$GatewayPid) {
    # Signal nothing but a live master started from this exact executable with
    # this exact prefix/config; arguments are compared as whole tokens, never
    # as substrings of the command line.
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $GatewayPid" -ErrorAction SilentlyContinue
    if (-not $proc) {
        throw "Pid $GatewayPid is not running. Stale gateway pid at $pidFile; inspect and remove it manually."
    }
    $exe = [string]$proc.ExecutablePath
    if (-not $exe -or -not [string]::Equals($exe.Replace('/', '\'), $nginx.Replace('/', '\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Pid $GatewayPid ($exe) was not started from $nginx. Refusing to signal it; inspect $pidFile manually."
    }
    $tokens = Split-CommandLine ([string]$proc.CommandLine)
    $usedPrefix = Get-CommandLineArgument $tokens '-p'
    $usedConfig = Get-CommandLineArgument $tokens '-c'
    if (-not $usedPrefix -or -not [string]::Equals($usedPrefix.Replace('\', '/').TrimEnd('/'), $prefix.Replace('\', '/').TrimEnd('/'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Pid $GatewayPid runs with prefix '$usedPrefix' instead of '$prefix'. Refusing to signal it; inspect $pidFile manually."
    }
    if (-not $usedConfig -or -not [string]::Equals($usedConfig, 'nginx.conf', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Pid $GatewayPid runs with config '$usedConfig' instead of nginx.conf. Refusing to signal it; inspect $pidFile manually."
    }
}

function Wait-ProcessExit([int]$GatewayPid, [int]$TimeoutSeconds) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while (Get-Process -Id $GatewayPid -ErrorAction SilentlyContinue) {
        if ((Get-Date) -gt $deadline) { return $false }
        Start-Sleep -Milliseconds 250
    }
    return $true
}

function Clear-LaunchedInstance([int]$MasterPid, [int]$TimeoutSeconds) {
    # Failed-start cleanup: touches only the master this invocation launched
    # (via -PassThru) and that master's direct children.
    if (Get-Process -Id $MasterPid -ErrorAction SilentlyContinue) {
        if ((Read-PidFile) -eq [string]$MasterPid) {
            & $nginx -p $prefix -c nginx.conf -s stop
            if ($LASTEXITCODE -eq 0) { Wait-ProcessExit $MasterPid $TimeoutSeconds | Out-Null }
        }
        if (Get-Process -Id $MasterPid -ErrorAction SilentlyContinue) {
            Stop-Process -Id $MasterPid -Force -ErrorAction SilentlyContinue
        }
    }
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $MasterPid" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if (-not (Get-Process -Id $MasterPid -ErrorAction SilentlyContinue) -and (Read-PidFile) -eq [string]$MasterPid) {
        Remove-Item -LiteralPath $pidFile
    }
}

# Stop/reload use the existing configuration; never overwrite a running
# instance's pid/listen settings or issue a signal with an unrelated prefix.
if ($Action -eq 'Stop' -or $Action -eq 'Reload') {
    if (-not (Test-Path -LiteralPath $config) -or -not (Test-Path -LiteralPath $pidFile)) {
        throw "No gateway instance configuration/pid in $runtime"
    }
    if ($Action -eq 'Reload') {
        & $nginx -p $prefix -c nginx.conf -t
        if ($LASTEXITCODE -ne 0) { throw 'Nginx configuration validation failed' }
    }
    $pidText = [IO.File]::ReadAllText($pidFile).Trim()
    if ($pidText -notmatch '^[0-9]+$') {
        throw "Gateway pid file $pidFile contains no numeric pid ('$pidText'); inspect it manually."
    }
    $gatewayPid = [int]$pidText
    Assert-GatewayMaster $gatewayPid
    $signal = if ($Action -eq 'Stop') { 'quit' } else { 'reload' }
    & $nginx -p $prefix -c nginx.conf -s $signal
    if ($LASTEXITCODE -ne 0) { throw "Nginx $Action failed" }
    if ($Action -eq 'Reload') {
        Write-Host "Gateway reload signaled (pid $gatewayPid)."
        return
    }
    if (-not (Wait-ProcessExit $gatewayPid $stopTimeoutSeconds)) {
        throw "Gateway pid $gatewayPid did not exit within $stopTimeoutSeconds seconds. Inspect $runtime\logs and stop it manually."
    }
    if ((Read-PidFile) -eq [string]$gatewayPid) { Remove-Item -LiteralPath $pidFile }
    Write-Host "Gateway stopped (pid $gatewayPid)."
    return
}
if (Test-Path -LiteralPath $pidFile) {
    $existingPid = [IO.File]::ReadAllText($pidFile).Trim()
    if ($existingPid) {
        throw 'Gateway pid already exists. Use Reload/Stop; inspect a stale pid before removing it.'
    }
    # nginx -t can create an empty pid file without starting an instance.
    Remove-Item -LiteralPath $pidFile
}
& "$projectRoot/server/.venv/Scripts/python.exe" "$projectRoot/deploy/nginx/render.py" `
    --output $runtime --frontend $FrontendDir --port $Port --upstream "127.0.0.1:$ApiPort"
if ($LASTEXITCODE -ne 0) { throw 'Gateway configuration generation failed' }
& $nginx -p $prefix -c nginx.conf -t
if ($LASTEXITCODE -ne 0) { throw 'Nginx configuration validation failed' }
if ($Action -eq 'Test') {
    if ((Test-Path -LiteralPath $pidFile) -and -not [IO.File]::ReadAllText($pidFile).Trim()) {
        Remove-Item -LiteralPath $pidFile
    }
    return
}
# Refuse to start into a port that another process already listens on; on
# Windows nginx could otherwise appear started while that process keeps the port.
$busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($busy) {
    $owner = ($busy | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Port $Port is already in use by PID $owner. Choose another -Port or stop that listener."
}
# Nginx owns its background lifecycle. Launch hidden, then verify this exact
# instance wrote its pid, stayed alive and owns the loopback listener before
# reporting success.
$startArgs = '-p "' + $prefix + '" -c nginx.conf'
$master = Start-Process -FilePath $nginx -ArgumentList $startArgs -WorkingDirectory $runtime -WindowStyle Hidden -PassThru
$masterPid = $master.Id
$deadline = (Get-Date).AddSeconds($startupTimeoutSeconds)
while ($true) {
    if (-not (Get-Process -Id $masterPid -ErrorAction SilentlyContinue)) {
        Clear-LaunchedInstance $masterPid 5
        throw "Nginx exited during startup (pid $masterPid). See $runtime\logs\error.log."
    }
    if ((Read-PidFile) -eq [string]$masterPid) {
        $listeners = Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort $Port -ErrorAction SilentlyContinue
        if ($listeners) {
            # The listener must belong to this master or its workers, not to
            # another process that grabbed the port first.
            $family = @($masterPid)
            $family += @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $masterPid" -ErrorAction SilentlyContinue | ForEach-Object { $_.ProcessId })
            $foreign = @($listeners | ForEach-Object { $_.OwningProcess } | Where-Object { $family -notcontains $_ })
            if (-not $foreign) { break }
            Clear-LaunchedInstance $masterPid 5
            throw "Port $Port is already in use by PID $($foreign -join ', '); the newly started gateway has been stopped."
        }
    }
    if ((Get-Date) -gt $deadline) {
        Clear-LaunchedInstance $masterPid 5
        throw "Gateway startup was not confirmed within $startupTimeoutSeconds seconds (pid $masterPid). See $runtime\logs\error.log."
    }
    Start-Sleep -Milliseconds 250
}
Write-Host "Gateway running: http://127.0.0.1:$Port (API 127.0.0.1:$ApiPort), pid $masterPid."
