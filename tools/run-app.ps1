param([string]$ConfigFile)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& npm.cmd --prefix "$projectRoot/admin" run build
if ($LASTEXITCODE -ne 0) { throw 'Management UI build failed' }
Write-Host 'Management UI and API: http://127.0.0.1:8000'
& "$PSScriptRoot/run-server.ps1" -ConfigFile $ConfigFile
exit $LASTEXITCODE
