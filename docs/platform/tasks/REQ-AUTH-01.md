# REQ-AUTH-01

- Task: T1.5, T1.9 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator / impl-backend (B), impl-frontend (F), test-writer (T), security-reviewer (Fable) review
- Files owned: `bridge/auth/`, `frontend/app/(public)/`, `frontend/e2e/auth.spec.ts`
- Depends on: T1.4.

## Scope

argon2id (m=64 MiB, t=3) signup/login, magic links (single use, 15 min), server-side sessions (`httpOnly; Secure; SameSite=Lax`, 30 days) with signed double-submit CSRF, login throttle 5/min per IP and per account, TOTP enrol/verify with recovery codes, TOTP mandatory for org owner/admin/signatory/reviewer and staff, step-up helper (MFA within 12 h). OAuth moved to REQ-AUTH-02 (D-20). Signup/login UI, Playwright E2E (Pixel 5 at 360 px and desktop) with axe.

## Acceptance criteria and tests

AC-SEC-1/a (cross-tenant API 404); X1-1 signup/login E2E on the compose stack; unit tests in `backend/tests/unit/auth/`.

## Notes

Signup always answers 202 "check your email" (no account enumeration); the verification link signs the user in.
