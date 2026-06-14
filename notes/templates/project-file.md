---
# ===== #Project-File archetype =====
# All values are FLAT scalars/strings so n8n can parse them with a regex or
# gray-matter without instantiating a vector DB. Keep keys lowercase_snake.
type: project                      # discriminator -> "project" | "learning"
title: "Migrate billing to Stripe"
status: active                     # active | blocked | dormant | done
priority: high                     # high | medium | low
deadline: 2026-07-01               # ISO-8601 date, empty string if none
last_actionable_date: 2026-06-09   # last day YOU touched it (drives staleness)
owner: ian
tags: [billing, infra]
stale_after_days: 5                # per-note override of the global threshold
---

# Migrate billing to Stripe

## Objective
One or two sentences on the desired end state.

## Current state
- Webhook signing implemented.
- Sandbox keys wired into staging.

## Next actions
- [ ] Map legacy plan IDs to Stripe Price objects
- [ ] Backfill customer records

## Recent log
- 2026-06-09 — Verified webhook signatures against test events.
- 2026-06-05 — Spiked the Checkout session flow.
