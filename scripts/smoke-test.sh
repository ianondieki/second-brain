#!/usr/bin/env bash
# Quick end-to-end sanity checks for the Second Brain stack.
# Usage:  source .env  &&  ./scripts/smoke-test.sh
# Works in WSL / Git Bash on the Windows host. Requires curl.
set -euo pipefail

: "${EVOLUTION_API_KEY:?set EVOLUTION_API_KEY (source your .env)}"
: "${EVOLUTION_INSTANCE:=secondbrain}"
: "${WA_TARGET_NUMBER:?set WA_TARGET_NUMBER}"
EVO="http://localhost:8080"

echo "==> Container memory (should be well under the limits):"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" || true

echo "==> n8n health:"
curl -fsS http://localhost:5678/healthz && echo " OK" || echo " n8n not ready"

echo "==> WhatsApp connection state:"
curl -fsS -H "apikey: ${EVOLUTION_API_KEY}" \
  "${EVO}/instance/connectionState/${EVOLUTION_INSTANCE}" || true
echo

echo "==> Sending a test WhatsApp message to ${WA_TARGET_NUMBER}:"
curl -fsS -X POST "${EVO}/message/sendText/${EVOLUTION_INSTANCE}" \
  -H "apikey: ${EVOLUTION_API_KEY}" -H "Content-Type: application/json" \
  -d "{\"number\":\"${WA_TARGET_NUMBER}\",\"text\":\"*Second Brain* smoke-test ✅\",\"delay\":1000}"
echo
echo "Done. If the message arrived, the local gateway path is healthy."
