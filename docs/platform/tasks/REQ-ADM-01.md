# REQ-ADM-01

- Task: T2.6b, T2.3 (queue parts only; the full console is Phase 8) (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (F4)
- Files owned: `bridge/admin/{deps,router,claims,moderation}.py`, `frontend/app/(admin)/`
- Depends on: T2.1.

## Scope

Phase 2 part: the `/admin` console shell (separate from both portals) with the claim queue (2 BD SLA shown), the moderation queue and the D2 KYC review queue; the staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff; Phase 1 follow-up 5); every decision audited. Impersonation, flags, refunds, research approval and the rest are Phase 8.

## Acceptance criteria and tests

Phase 2 tests: `integration/admin/test_moderation_queue.py`, `integration/directory/test_claims.py`. AC-ADM-3 is Phase 8.
