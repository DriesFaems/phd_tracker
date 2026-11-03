# Starts the PhD Tracker in production mode from the project's own virtual environment.
# Host and port come from APP_HOST / APP_PORT in .env (defaults: 0.0.0.0:80). Output goes to logs\server.log.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$appHost = "0.0.0.0"; $appPort = "80"
if (Test-Path "$root\.env") {
    foreach ($line in Get-Content "$root\.env") {
        if ($line -match '^\s*APP_HOST\s*=\s*(.+?)\s*$') { $appHost = $Matches[1] }
        if ($line -match '^\s*APP_PORT\s*=\s*(.+?)\s*$') { $appPort = $Matches[1] }
    }
}

New-Item -ItemType Directory -Force "$root\logs" | Out-Null
$log = "$root\logs\server.log"
if ((Test-Path $log) -and (Get-Item $log).Length -gt 10MB) { Move-Item $log "$log.old" -Force }

"$(Get-Date -Format s) starting on ${appHost}:${appPort}" | Add-Content $log
# Run through cmd so uvicorn's normal stderr output is not treated as a PowerShell error.
$python = "$root\.venv\Scripts\python.exe"
cmd /c "`"$python`" -m uvicorn app.main:app --host $appHost --port $appPort --workers 1 --no-access-log >> `"$log`" 2>&1"
exit $LASTEXITCODE
