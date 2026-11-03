# Run ONCE in an *administrator* PowerShell, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
#
# Registers two Windows scheduled tasks:
#   "PhD Tracker"        - starts the web app at boot (as SYSTEM) and restarts it if it stops
#   "PhD Tracker backup" - daily database backup at 02:00 into the backups folder (keeps 30)
# Remove them again with:  Unregister-ScheduledTask -TaskName "PhD Tracker*" -Confirm:$false
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Web app: at startup, never time out, restart every minute on failure (up to 999 times).
$appAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run_server.ps1`"" -WorkingDirectory $root
$appSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "PhD Tracker" -Description "PhD supervision web app (http://$env:COMPUTERNAME)" `
    -Action $appAction -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $appSettings -Principal $principal -Force | Out-Null

# Daily backup.
$backupAction = New-ScheduledTaskAction -Execute "$root\.venv\Scripts\python.exe" -Argument "-m scripts.backup" -WorkingDirectory $root
Register-ScheduledTask -TaskName "PhD Tracker backup" -Description "Daily SQLite backup of the PhD Tracker" `
    -Action $backupAction -Trigger (New-ScheduledTaskTrigger -Daily -At 2am) -Principal $principal -Force | Out-Null

# Take over from an instance started by hand (it would hold the port).
$venvPython = "$root\.venv\Scripts\python.exe"
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.ExecutablePath -eq $venvPython -and $_.CommandLine -like "*uvicorn app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped running instance (PID $($_.ProcessId))" }
Start-Sleep -Seconds 2

Start-ScheduledTask -TaskName "PhD Tracker"
Start-Sleep -Seconds 8
try {
    $code = (Invoke-WebRequest "http://localhost/login" -UseBasicParsing -TimeoutSec 15).StatusCode
    Write-Host "PhD Tracker is running (HTTP $code). Open http://$($env:COMPUTERNAME.ToLower())" -ForegroundColor Green
} catch {
    Write-Host "Tasks registered, but the app did not answer yet. Check $root\logs\server.log" -ForegroundColor Yellow
}
