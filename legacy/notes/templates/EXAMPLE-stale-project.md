---
# Copy this into your vault (notes/projects/) and set last_actionable_date to
# ~6+ days ago to trigger the nudge on the next manual/cron run. Demo only.
type: project
title: "Demo — Stripe billing migration"
status: active
priority: high
deadline: 2026-07-01
last_actionable_date: 2026-06-05
owner: ian
tags: [demo, billing]
stale_after_days: 5
---

# Demo — Stripe billing migration

## Next actions
- [ ] Map legacy plan IDs to Stripe Price objects
- [ ] Backfill customer records

## Recent log
- 2026-06-05 — Verified webhook signatures against test events.
- 2026-06-03 — Wired sandbox keys into staging.
