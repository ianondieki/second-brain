# REQ-NOT-02

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-integrations
- Files owned: `bridge/notifications/templates/em1.*`, `bridge/notifications/em1.py`
- Depends on: T2.4 (receipt, hash), T2.7 tags.

## Scope

EM1 "Proposal submitted + disclosure record": subject `Your proposal "{{title}}" is registered and sent to {{sent_count}} organisations`; receipt id (cert id), hash or "timestamp pending", sent-to (delivered) and saved-for (held) groups; single CTA, plain-text part, footer (Manage notifications · Help · Nairobi, Kenya). Escaped fields, no auto-linkable contact data, copy-lint clean, Mailpit only.

## Acceptance criteria and tests

The AC-PROP-1/a EM1 clause (`unit/notifications/test_em1.py`, `integration/proposals/test_tags.py::test_mixed_tags`).

## Prototype P4 (2026-09-29): built

- `bridge/notifications/em1.py` with `templates/em1.txt.j2` and `templates/em1.html.j2` (`[[COPY-REVIEW]]`): subject
  `Your proposal "<title>" is registered and sent to N organisation(s)` (singular for 1); receipt id (cert id); hash
  once the version is timestamped, else "Timestamp pending"; "Sent to (N, verified)" and "Saved for (N)" groups with
  the held reason (the E0 sentence is docs/spec/06 6.2's); one call to action (`data-cta`, "Open your proposal" to
  `/dev/ideas/<id>`); plain-text part; footer (product, receipt, Manage notifications · Help · Nairobi, Kenya). The
  HTML part autoescapes; titles and organisation names are neutralised (`unlinkable`: one line, dots between word
  characters become U+2024, "@" U+FF20, "://" ":") so no mail client links them; the only links are the platform's.
  Copy-lint clean. English only (D-27).
- Sent to the developer only, after the response (`BackgroundTasks` + `em1.deliver`, own transaction bound to the
  developer, the delivery ledger, kind `em1`, dedupe key per Pitch), only when a Pitch delivered at least one tag; a
  failure is logged without the address and never raised. In dev it reaches Mailpit through the existing SMTP
  provider; tests use the fake.
- Tests: `unit/notifications/test_em1.py` (subject, counts, one-line subject, receipt and timestamp states, groups,
  one CTA, footer, escaping, nothing auto-linkable, dedupe key), `integration/proposals/test_tags.py::test_mixed_tags`
  (the AC-PROP-1/a EM1 clause, exactly once, developer only) and `::test_a_second_pitch_sends_its_own_em1`,
  `integration/notifications/test_em1_delivery.py` (never raises, logs without the address, once per key).

Recipient note: EM1 goes to the developer (docs/spec/06 6.10, `REQUIREMENTS.md` §5 N01), not to the organisation (the
P4 brief said the organisation's reviewers; see REQ-PROP-03 "Deviation"). The organisation's N01 in-app line is
REQ-NOT-03's and needs a database function (REQ-PROP-03 "Schema needs").

After prototype: the i18n keys, the Swahili version (D-27), the worker path that commits a queued claim before sending
(REQ-NOT-06).
