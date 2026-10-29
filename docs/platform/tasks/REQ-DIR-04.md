# REQ-DIR-04

- Task: T2.6c (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-integrations (email headers)
- Files owned: `bridge/directory/invitations.py`, `bridge/notifications/suppressions.py`, invitation templates
- Depends on: T2.1, T2.6a, T2.7 (held tags).

## Scope

Held tags for E0 orgs send zero emails. Invitations: at most one aggregated, content-free, admin-approved invitation per org per 30 days and two per lifetime, only to a published role address (local-part allow-list: partnerships, innovation, info, …), with sender identity, the physical address (`COMPANY_POSTAL_ADDRESS`, placeholder until G2), `List-Unsubscribe` and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) to a permanent suppression; an opted-out org is never invited again. Invitation copy is tagged `[[COPY-REVIEW]]`, passes the copy-lint and goes to Mailpit only. Delisting on request releases held tags with a notice to the developer.

## Acceptance criteria and tests

AC-DIR-1 (`integration/directory/test_held_tags.py`), AC-DIR-4 (`integration/directory/test_invitations.py`).

## Prototype P4 (2026-09-29): held tags built; invitations after prototype

- E0 tags are `held_unclaimed`, E1 tags `held_pending_verification` (`bridge/proposals/tags.py`); a held tag creates
  no engagement and no grant, sends no email (EM1 only when a Pitch delivered something) and writes no in-app row;
  the developer sees the spec's sentence ("{Org} isn't on the platform yet. Your proposal is saved and they'll see it
  if they join and verify. We don't email them on your behalf.") and can withdraw a held tag.
- Tests: `integration/directory/test_held_tags.py` (AC-DIR-1: zero emails in the mail sink and the delivery ledger, no
  in-app row, no hook call, no `directory_invitations` row; E1 members see only the count).

After prototype (unchanged scope): invitations (AC-DIR-4), suppressions, delisting's notice to the developer.
