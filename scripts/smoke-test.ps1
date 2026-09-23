<#
  Quick end-to-end sanity checks for the Second Brain stack (native PowerShell).
  Run from the repo root after `docker compose up -d`:
      ./scripts/smoke-test.ps1
  Reads values from the .env file next to docker-compose.yml.
#>
$ErrorActionPreference = 'Stop'

# --- Load .env (KEY=VALUE lines) ---
$envPath = Join-Path $PSScriptRoot '..\.env'
if (-not (Test-Path $envPath)) { throw "No .env found at $envPath. Copy .env.example to .env first." }
$cfg = @{}
Get-Content $envPath | ForEach-Object {
    if ($_ -match '^\s*#') { return }
    if ($_ -match '^\s*([^=\s]+)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
}
$token  = $cfg['TELEGRAM_BOT_TOKEN']
$chatId = $cfg['TELEGRAM_CHAT_ID']
$tg     = "https://api.telegram.org/bot$token"

Write-Host "==> Container memory:" -ForegroundColor Cyan
docker stats --no-stream --format "table {{.Name}}`t{{.MemUsage}}`t{{.MemPerc}}"

Write-Host "`n==> n8n health:" -ForegroundColor Cyan
try { Invoke-RestMethod "http://localhost:5678/healthz" -TimeoutSec 5 | Out-Null; Write-Host " OK" -ForegroundColor Green }
catch { Write-Host " n8n not ready: $($_.Exception.Message)" -ForegroundColor Yellow }

Write-Host "`n==> Telegram bot identity (getMe):" -ForegroundColor Cyan
try {
    Invoke-RestMethod "$tg/getMe" -TimeoutSec 10 | ConvertTo-Json -Depth 5
} catch { Write-Host " could not query getMe: $($_.Exception.Message)" -ForegroundColor Yellow }

Write-Host "`n==> Sending a test Telegram message to chat $chatId :" -ForegroundColor Cyan
$body = @{ chat_id = $chatId; text = "<b>Second Brain</b> smoke-test OK"; parse_mode = "HTML" } | ConvertTo-Json
try {
    Invoke-RestMethod "$tg/sendMessage" -Method Post `
        -Headers @{ 'Content-Type' = 'application/json' } -Body $body -TimeoutSec 20 |
        ConvertTo-Json -Depth 5
    Write-Host "Done. If the message arrived, the Telegram delivery path is healthy." -ForegroundColor Green
} catch { Write-Host " send failed: $($_.Exception.Message)" -ForegroundColor Red }
