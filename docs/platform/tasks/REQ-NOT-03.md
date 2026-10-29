# REQ-NOT-03

- Requirement: notification dispatch generated from the state machine for N01–N23 (except N02), in-app always, email
  per preference, 🔒 events unmutable, WhatsApp stubbed for R2 (`REQUIREMENTS.md` §3, §5).
- Status: partly built across P5 (`bridge/engagements/notify.py`), P19-A (side states and the expiry job's events,
  the status-change email `bridge/notifications/status.py`) and P19-C (the in-app channel's reads). This card records
  what is still open; the full plan is written when the dispatch is scheduled.

## Open: role-seat dispatch (the organisation's recipients)

Today the tracker tells the organisation's **people on the engagement**: its named contact and every member who
acted on it, each re-checked as an active member (`notify.org_people`). The notification job runs bound to the
developer, who cannot read the organisation's roster (RLS), so an engagement nobody at the organisation has touched
yet tells nobody there. That leaves these matrix recipients unserved:

- N01 (enter SUBMITTED): the organisation's reviewer seats or the niche's default assignee (the inbox shows it);
- N01 (expiry): `SUBMITTED` reaches 20 BD → `EXPIRED (NO_REVIEW)`: the **org admin** (only the developer is told when
  nobody at the organisation acted);
- N03 (expiry): `UNDER_REVIEW` reaches 30 BD → `EXPIRED (NO_DECISION)`: the **org admin** (told only when they acted);
- N05: escalation to the org admin at +3 BD (not built), EM6 to both sides (REQ-NOT-05).

Needed: a dispatch step that resolves role seats (owner and admin, reviewer seats, a niche's default assignee) without
binding to a user who may not read them: a SECURITY DEFINER function returning the user ids of an organisation's
active members in given roles for an engagement event, EXECUTE for the notification job only (a db-migrations
revision), then one bound session per recipient as today. Until then the gap is recorded in `THREAT_MODEL.md` (E,
the notification job) and on the P19-A card.
