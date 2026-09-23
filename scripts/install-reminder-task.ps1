<#
  Registers the daily project reminder with Windows Task Scheduler (current user, no admin).

      powershell -ExecutionPolicy Bypass -File scripts\install-reminder-task.ps1

  Runs `pythonw -m reminder` (no console window):
    - every 30 minutes from 08:00 to 23:00, and
    - 3 minutes after you log on,
  and catches up after sleep/shutdown ("run as soon as possible after a missed start").
  The script itself sends each channel at most once per day, so frequent runs are safe.
  Remove with scripts\uninstall-reminder-task.ps1.
#>
param(
    [string]$Python = "",
    [string]$TaskName = "SecondBrain Project Reminder"
)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

if (-not $Python) {
    # The project venv holds LangGraph; fall back to a bare interpreter only if it is missing.
    $candidates = @((Join-Path $repo '.venv\Scripts\pythonw.exe'), "C:\Python313\pythonw.exe")
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $Python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Python -or -not (Test-Path $Python)) { throw "pythonw.exe not found. Pass -Python C:\path\to\pythonw.exe" }

# Prove the interpreter can import the workflow (incl. LangGraph) before scheduling it.
$console = Join-Path (Split-Path $Python) 'python.exe'
Push-Location $repo
try {
    & $console -c "import reminder.graph" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "$console cannot import reminder.graph. Create the venv first: python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
} finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $Python -Argument '-m reminder' -WorkingDirectory $repo

$daily = New-ScheduledTaskTrigger -Daily -At '08:00'
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At '08:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Hours 15)).Repetition

$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT3M'

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 25) -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$task = New-ScheduledTask -Action $action -Trigger @($daily, $logon) -Settings $settings -Principal $principal `
    -Description "Daily email + WhatsApp reminder about projects that have gone cold. Repo: $repo"

try {
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
} catch {
    Write-Host "Log-on trigger was refused ($($_.Exception.Message)); registering the daily schedule only." -ForegroundColor Yellow
    $task = New-ScheduledTask -Action $action -Trigger @($daily) -Settings $settings -Principal $principal `
        -Description "Daily email + WhatsApp reminder about projects that have gone cold. Repo: $repo"
    Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
}

$info = Get-ScheduledTask -TaskName $TaskName
Write-Host "Registered '$TaskName' ($($info.State)) -> $Python -m reminder (in $repo)" -ForegroundColor Green
Write-Host "Triggers: $(( $info.Triggers | ForEach-Object { $_.CimClass.CimClassName -replace 'MSFT_Task','' -replace 'Trigger','' }) -join ', ')"
Write-Host "Logs: $repo\.state\remind.log"
