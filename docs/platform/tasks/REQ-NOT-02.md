# REQ-NOT-02

- Task: T2.7 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-integrations
- Files owned: `bridge/notifications/templates/em1.*`, `bridge/notifications/em1.py`
- Depends on: T2.4 (receipt, hash), T2.7 tags.

## Scope

EM1 "Proposal submitted + disclosure record": subject `Your proposal "{{title}}" is registered and sent to {{sent_count}} organisations`; receipt id (cert id), hash or "timestamp pending", sent-to (delivered) and saved-for (held) groups; single CTA, plain-text part, footer (Manage notifications · Help · Nairobi, Kenya). Escaped fields, no auto-linkable contact data, copy-lint clean, Mailpit only.

## Acceptance criteria and tests

The AC-PROP-1/a EM1 clause (`unit/notifications/test_em1.py`, `integration/proposals/test_tags.py::test_mixed_tags`).
