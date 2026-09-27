# REQ-DIR-04

- Task: T2.6c (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-integrations (email headers)
- Files owned: `bridge/directory/invitations.py`, `bridge/notifications/suppressions.py`, invitation templates
- Depends on: T2.1, T2.6a, T2.7 (held tags).

## Scope

Held tags for E0 orgs send zero emails. Invitations: at most one aggregated, content-free, admin-approved invitation per org per 30 days and two per lifetime, only to a published role address (local-part allow-list: partnerships, innovation, info, …), with sender identity, the physical address (`COMPANY_POSTAL_ADDRESS`, placeholder until G2), `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) to a permanent suppression; an opted-out org is never invited again. Invitation copy is tagged `[[COPY-REVIEW]]`, passes the copy-lint and goes to Mailpit only. Delisting on request releases held tags with a notice to the developer.

## Acceptance criteria and tests

AC-DIR-1 (`integration/directory/test_held_tags.py`), AC-DIR-4 (`integration/directory/test_invitations.py`).
