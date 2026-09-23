<#
  Removes the scheduled project reminder. Your settings (reminders.json), .env and
  .state logs are left untouched.

      powershell -ExecutionPolicy Bypass -File scripts\uninstall-reminder-task.ps1
#>
param([string]$TaskName = "SecondBrain Project Reminder")
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'." -ForegroundColor Green
} else {
    Write-Host "No task named '$TaskName' is registered."
}
