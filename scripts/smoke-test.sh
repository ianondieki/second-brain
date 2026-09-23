#!/usr/bin/env bash
# Quick end-to-end sanity checks for the Second Brain stack.
# Usage:  source .env  &&  ./scripts/smoke-test.sh
# Works in WSL / Git Bash on the Windows host. Requires curl.
set -euo pipefail

: "${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN (source your .env)}"
: "${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID}"
TG="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"

echo "==> Container memory (should be well under the limit):"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" || true

echo "==> n8n health:"
curl -fsS http://localhost:5678/healthz && echo " OK" || echo " n8n not ready"

echo "==> Telegram bot identity (getMe):"
curl -fsS "${TG}/getMe" || true
echo

echo "==> Sending a test Telegram message to chat ${TELEGRAM_CHAT_ID}:"
curl -fsS -X POST "${TG}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"${TELEGRAM_CHAT_ID}\",\"text\":\"<b>Second Brain</b> smoke-test ✅\",\"parse_mode\":\"HTML\"}"
echo
echo "Done. If the message arrived, the Telegram delivery path is healthy."
