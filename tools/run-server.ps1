param([string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if ($ConfigFile) {
    foreach ($line in Get-Content -LiteralPath $ConfigFile -Encoding utf8) {
        $entry = $line.Trim()
        if (-not $entry -or $entry.StartsWith('#')) { continue }
        $parts = $entry.Split('=', 2)
        if ($parts.Length -ne 2 -or $parts[0] -notmatch '^APP_[A-Z0-9_]+$') {
            throw 'Invalid APP configuration entry'
        }
        [Environment]::SetEnvironmentVariable($parts[0], $parts[1].Trim(), 'Process')
    }
}
& "$projectRoot/server/.venv/Scripts/python.exe" -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1
exit $LASTEXITCODE
