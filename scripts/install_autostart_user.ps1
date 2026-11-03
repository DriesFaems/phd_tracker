# No administrator rights needed. Run once in a normal PowerShell, from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart_user.ps1
#
# Starts the PhD Tracker under YOUR Windows account:
#   - now, and every time you sign in to this machine
#   - it keeps running while your session is merely disconnected (e.g. closing Remote Desktop),
#     but stops when you sign out or the machine reboots (then it starts again at your next sign-in)
# Also schedules a daily database backup at 02:00 (runs while you are signed in or disconnected).
#
# Prefers a scheduled task (restarts the app if it crashes); falls back to a Startup-folder shortcut
# if this account may not create tasks. Undo with:
#   Unregister-ScheduledTask -TaskName "PhD Tracker*" -Confirm:$false
#   Remove-Item "$([Environment]::GetFolderPath('Startup'))\PhD Tracker.lnk" -ErrorAction SilentlyContinue
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$me = "$env:USERDOMAIN\$env:USERNAME"
$runArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\run_server.ps1`""

# Stop an instance that is already running from this project (it would hold the port).
$venvPython = "$root\.venv\Scripts\python.exe"
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.ExecutablePath -eq $venvPython -and $_.CommandLine -like "*uvicorn app.main:app*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped running instance (PID $($_.ProcessId))" }
Start-Sleep -Seconds 2

$mode = $null
try {
    $principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "PhD Tracker" -Description "PhD supervision web app, runs while $me is signed in" `
        -Action (New-ScheduledTaskAction -Execute "powershell.exe" -Argument $runArgs -WorkingDirectory $root) `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $me) -Settings $settings -Principal $principal -Force | Out-Null
    Register-ScheduledTask -TaskName "PhD Tracker backup" -Description "Daily SQLite backup of the PhD Tracker" `
        -Action (New-ScheduledTaskAction -Execute $venvPython -Argument "-m scripts.backup" -WorkingDirectory $root) `
        -Trigger (New-ScheduledTaskTrigger -Daily -At 2am) -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName "PhD Tracker"
    $mode = "scheduled task"
} catch {
    Write-Host "Could not create a scheduled task ($($_.Exception.Message)); using the Startup folder instead." -ForegroundColor Yellow
    $lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "PhD Tracker.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $sc = $shell.CreateShortcut($lnk)
    $sc.TargetPath = "powershell.exe"
    $sc.Arguments = $runArgs
    $sc.WorkingDirectory = $root
    $sc.WindowStyle = 7
    $sc.Save()
    Start-Process powershell.exe -ArgumentList $runArgs -WorkingDirectory $root -WindowStyle Hidden
    $mode = "Startup-folder shortcut (no automatic restart or daily backup)"
}

Start-Sleep -Seconds 8
try {
    $code = (Invoke-WebRequest "http://localhost/login" -UseBasicParsing -TimeoutSec 15).StatusCode
    Write-Host "PhD Tracker is running via $mode (HTTP $code): http://$($env:COMPUTERNAME.ToLower())" -ForegroundColor Green
    Write-Host "Disconnect from Remote Desktop instead of signing out to keep it available." -ForegroundColor Green
} catch {
    Write-Host "Set up via $mode, but the app did not answer yet. Check $root\logs\server.log" -ForegroundColor Yellow
}
