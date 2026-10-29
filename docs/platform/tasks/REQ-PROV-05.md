# REQ-PROV-05

- Task: T2.10 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (F2)
- Files owned: `bridge/proposals/lifecycle.py`, the delete dialog in `frontend/app/(app)/dev/ideas/`
- Depends on: T2.3, T2.4.

## Scope

"Deleting" a registered proposal sets it `hidden` (gone from Tier-1 lists, search, the directory picker and Browse; Tier-2 grants stop) but keeps versions, manifests, provenance records, proofs and audit events; certificates and `/verify` keep working. The UI states this before confirming. Drafts that were never registered may be removed.

## Acceptance criteria and tests

AC-IP-6 (`integration/proposals/test_delete_retains.py`, `frontend/e2e/delete-notice.spec.ts`).

## Prototype P2 (2026-09-29): built

- `bridge/proposals/lifecycle.py`, `DELETE /api/me/proposals/{id}` (owner; 404 for anyone else): a proposal with a
  registered version becomes `hidden` (`hidden_at`; idempotent; audited `proposal.hidden`), keeping versions, Tier 2,
  manifests, provenance records, attestations, attachments and their objects, and audit events; the teaser and every
  Tier-1 read drop it, `app_tier2_granted` stops admitting it, and edits, publishing and uploads answer 409
  `proposal_hidden`; certificates and `/verify` keep working. A never-published draft is deleted with its version,
  Tier 2, links, attachments and uploaded objects (audited `proposal.draft_deleted`). The response carries the
  `[[COPY-REVIEW]]` message the UI shows.
- The three ownership attestations are recorded at every registration by the publish flow (`REQ-PROP-01.md`).
- Tests: `integration/proposals/test_delete_retains.py` (AC-IP-6 backend half).

## After prototype (rescheduled, not removed)

- The delete dialog stating the retention before confirming and `frontend/e2e/delete-notice.spec.ts` (F2, P8).
- What hiding does to open tags and engagements (Phase 3 tracker).
