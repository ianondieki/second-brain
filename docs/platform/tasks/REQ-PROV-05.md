# REQ-PROV-05

- Task: T2.10 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (F2)
- Files owned: `bridge/proposals/lifecycle.py`, the delete dialog in `frontend/app/(app)/dev/ideas/`
- Depends on: T2.3, T2.4.

## Scope

"Deleting" a registered proposal sets it `hidden` (gone from Tier-1 lists, search, the directory picker and Browse; Tier-2 grants stop) but keeps versions, manifests, provenance records, proofs and audit events; certificates and `/verify` keep working. The UI states this before confirming. Drafts that were never registered may be removed.

## Acceptance criteria and tests

AC-IP-6 (`integration/proposals/test_delete_retains.py`, `frontend/e2e/delete-notice.spec.ts`).
