# Section 3 — Resilient WhatsApp Web Bridging (Free Gateway)

The gateway is **Evolution API v2** (Baileys engine) — a headless,
open-source WhatsApp Web client exposed as a local HTTP API. No Meta Business
account, no paid Cloud API. It pairs to a **personal** WhatsApp number via QR.

> ⚠️ This drives a personal account through an unofficial Web client. Meta's
> ToS technically frowns on automation. The rate-limiting strategy below is
> what keeps a low-volume *personal* assistant under the radar. Do not blast
> broadcasts; this is one nudge to yourself per morning.

## 3.1 Create the instance & pair via QR

All calls carry the header `apikey: <EVOLUTION_API_KEY>` (from `.env`).

```powershell
# 1) Create the WhatsApp instance (name MUST equal EVOLUTION_INSTANCE in .env)
curl -X POST http://localhost:8080/instance/create ^
  -H "apikey: %EVOLUTION_API_KEY%" -H "Content-Type: application/json" ^
  -d "{ \"instanceName\": \"secondbrain\", \"integration\": \"WHATSAPP-BAILEYS\", \"qrcode\": true }"

# 2) Fetch a fresh QR (also returned by the create call). Returns base64 PNG + a
#    'pairingCode' you can type into the phone instead of scanning.
curl -X GET http://localhost:8080/instance/connect/secondbrain ^
  -H "apikey: %EVOLUTION_API_KEY%"
```

Scan the QR with **WhatsApp → Settings → Linked Devices → Link a Device**.
Easiest path: open the Evolution Manager UI at
<http://localhost:8080/manager> (log in with the API key), pick the
`secondbrain` instance, and scan the rendered QR.

Confirm the link is live:
```powershell
curl -X GET http://localhost:8080/instance/connectionState/secondbrain ^
  -H "apikey: %EVOLUTION_API_KEY%"
# -> { "instance": { "state": "open" } }
```

## 3.2 Smoke-test an outbound message
```powershell
curl -X POST http://localhost:8080/message/sendText/secondbrain ^
  -H "apikey: %EVOLUTION_API_KEY%" -H "Content-Type: application/json" ^
  -d "{ \"number\": \"2348012345678\", \"text\": \"*Second Brain* online ✅\" }"
```
`number` is E.164 **without** the `+`. To message yourself, use your own number.

## 3.3 Session resilience
- The Baileys auth state lives in the `evolution_instances` Docker volume, so
  `docker compose restart` keeps you logged in — no re-scan.
- WhatsApp expires a linked device after ~14 days **offline**. Keep the
  container running; the daily 08:00 job alone is enough to stay "seen".
- If `connectionState` ever returns `close`, hit `/instance/connect/{name}`
  again and re-scan. A small n8n monitor flow can ping this endpoint hourly and
  nudge you if it drops.

## 3.4 Anti-spam / rate-limiting strategy (inside n8n)

Meta flags *bursts* and *unsolicited* traffic. For a self-nudge assistant the
risk is low, but bake in these guards so any future fan-out stays safe:

1. **Per-message typing delay.** The send node sets `"delay": 1200` (ms) so
   Evolution emits a realistic "typing…" pause instead of an instant blast.
2. **Throttle / queue with a Loop + Wait.** If you ever send to >1 recipient,
   replace the single send node with a **Loop Over Items** → **Send** →
   **Wait (randomised 4–9 s)** sub-flow. Randomised jitter beats fixed
   intervals for looking human.
3. **Daily cap.** Keep a counter (Static Data via a Code node, or a Redis key)
   and hard-stop after N sends/day. For the morning nudge, N = 1.
4. **Only message numbers that have messaged you.** Never cold-DM. The whole
   design targets *your own* number.
5. **Backoff on errors.** Wire the send node's error output to a **Wait 60s →
   retry once** branch; if it still fails, stop — don't hammer.

```text
[Cron] -> [Read] -> [Filter] -> [LLM] -> [Loop Over Items]
                                              |-> [Send Text] -> [Wait 4–9s rand] --(loop)
                                              |-> (on error) [Wait 60s] -> [Send Text retry]
```
