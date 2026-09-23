<#
  Keeps the WhatsApp voice adviser running in the background (current user, no admin).

      powershell -ExecutionPolicy Bypass -File scripts\install-adviser-task.ps1 [-StartNow]

  Runs `pythonw -m adviser serve` (no console window):
    - 1 minute after you log on, and
    - every 15 minutes as a watchdog: if the adviser is already running, the new start is
      ignored (and the port check refuses a second copy anyway); if it crashed, it comes back.
  No time limit: it is meant to run all day. Logs: .state\adviser.log
  Run `.venv\Scripts\python.exe -m adviser check` first; WA_APP_SECRET must be in .env.
  Remove with scripts\uninstall-adviser-task.ps1.
#>
param(
    [string]$Python = "",
    [string]$TaskName = "SecondBrain WhatsApp Adviser",
    [switch]$StartNow
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not $Python) {
    $candidates = @((Join-Path $repo '.venv\Scripts\pythonw.exe'), "C:\Python313\pythonw.exe")
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $Python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Python -or -not (Test-Path $Python)) { throw "pythonw.exe not found. Pass -Python C:\path\to\pythonw.exe" }

# Prove the interpreter has everything and the settings are complete before scheduling it.
$console = Join-Path (Split-Path $Python) 'python.exe'
Push-Location $repo
try {
    & $console -m adviser check
    if ($LASTEXITCODE -ne 0) {
        throw "The adviser is not ready (see the unticked items above). Fix them, then run this script again."
    }
} finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $Python -Argument '-m adviser serve' -WorkingDirectory $repo

$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT1M'
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)

# Priority 5 (normal-ish), not Task Scheduler's default 7: at 7 Windows also gives the process low
# I/O and memory priority, and on this laptop a scheduled run has been starved for minutes while
# other work was running. This one has to answer the owner within seconds.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -Priority 5

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger @($logon, $watchdog) -Settings $settings -Principal $principal `
    -Description "Two-way WhatsApp adviser (text + voice notes) for your projects. Repo: $repo"

try {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
} catch {
    Write-Host "Log-on trigger was refused ($($_.Exception.Message)); registering the watchdog only." -ForegroundColor Yellow
    $task = New-ScheduledTask -Action $action -Trigger @($watchdog) -Settings $settings -Principal $principal `
        -Description "Two-way WhatsApp adviser (text + voice notes) for your projects. Repo: $repo"
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
}

if ($StartNow) { Start-ScheduledTask -TaskName $TaskName }

$info = Get-ScheduledTask -TaskName $TaskName
Write-Host "Registered '$TaskName' ($($info.State)) -> $Python -m adviser serve (in $repo)" -ForegroundColor Green
Write-Host "Logs: $repo\.state\adviser.log   Current webhook address: $repo\.state\adviser\public_url.txt"
