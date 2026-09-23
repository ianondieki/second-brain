<#
  Stops and removes the WhatsApp adviser task. Settings (.env), memory and logs in .state
  are left untouched. Meta keeps the last webhook address; with the adviser gone, messages
  to it simply go unanswered.

      powershell -ExecutionPolicy Bypass -File scripts\uninstall-adviser-task.ps1
#>
param([string]$TaskName = "SecondBrain WhatsApp Adviser")
$ErrorActionPreference = 'Stop'
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'." -ForegroundColor Green
} else {
    Write-Host "No task named '$TaskName' is registered."
}
# pythonw.exe and cloudflared.exe started by the task may outlive it; stop the ones from this repo.
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='cloudflared.exe'" |
    Where-Object { $_.CommandLine -like '*-m adviser serve*' -or $_.ExecutablePath -like "$repo\tools\*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped $($_.Name) ($($_.ProcessId))." }
