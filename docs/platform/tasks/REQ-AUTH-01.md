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

## Phase 2 follow-ups (from the Phase 1 report; picked up in Phase 2)

1. JS budget: send CSP and Permissions-Policy on page responses only (not on `/_next/static`), drop legacy polyfills with a modern browserslist target, and state in `docs/runbooks/dev-setup.md` and the budget test whether 150 KB means KB (1000) or KiB.
2. Local E2E: pin `workers: 1` (or a longer web-server step) for local runs so argon2 hashing in the single API process does not time out; CI unchanged.
3. Password forms: a hidden `autocomplete="username"` field so password managers save the right account.
4. `/settings/security`: hide the Password section while two-step enrolment is in progress.
5. The staff dependency (staff role + enrolled and verified TOTP; 404 for non-staff) ships with the first `/admin` route (REQ-ADM-01, T2.3/T2.6b).
6. The enforced nonce CSP, HSTS and the report-only CSP's report endpoint stay in Phase 8 (REQ-SEC-03).
7. Backend (`bridge/auth/`, security-reviewer review): a pending TOTP secret (`users.totp_pending_enc`) outlives
   "Cancel setup" and a closed tab (`THREAT_MODEL.md` §1, "A pending TOTP secret lingers"). Clear it on cancel or
   give it a TTL: a CSRF-checked `DELETE /api/auth/totp/enrol` that "Cancel setup" calls (the web client sends
   DELETE), and/or a pending-since timestamp that `confirm_totp_enrolment` checks, clearing a secret older than 15
   minutes (the magic-link lifetime) so an abandoned tab is covered too. A new column goes through `db-migrations`.
   Tests: after cancel or expiry, confirming answers 409 `no_pending_enrolment` and the column is empty. Then narrow
   that threat-model row's residual risk.
   The DELETE also settles "Cancel setup" after a confirmation whose answer was lost (`THREAT_MODEL.md` §1, "Cancel
   setup reads 'off' before a lost confirmation commits"): it takes `lock_user` like `confirm_totp_enrolment`, so the
   two serialise, and answers 409 `totp_already_enabled` when two-step sign-in is on (the pending secret is then
   already gone). The web client's Cancel acts on that answer instead of asking GET /api/auth/me: 409
   `totp_already_enabled` goes to the "on" screen with the codes-not-shown notice, success to the "cancelled" notice,
   anything else (no answer, 5xx, timeout) keeps the setup steps with the status-unknown notice. Tests: a confirm and
   a DELETE racing on one user end either with two-step sign-in off and nothing pending, or with it on and the DELETE
   answering 409 `totp_already_enabled`; the frontend tests replace the GET /me mocks of the lost-answer cases.
8. Backend (`bridge/auth/`, security-reviewer review), then `/settings/security`: new recovery codes. When the
   confirmation's answer is lost after the commit, the person has two-step sign-in on and recovery codes they never
   saw; a role that requires two-step sign-in cannot turn it off and set it up again, so today it has no way to get
   codes (`THREAT_MODEL.md` §1, "Recovery codes never seen after a lost confirmation"). Add a CSRF-checked route that
   issues ten new recovery codes and replaces the old ones in one step, behind the step-up helper (MFA within 12 h),
   with an `auth.recovery_codes_replaced` audit event and a security-notice email ("New recovery codes were
   created."). Then a "Get new recovery codes" action on the "on" screen; the codes-not-shown notices
   (`security.codesNotShown`, `security.codesNotShownTurnOff`) point at it, the latter no longer sending people to
   turn two-step sign-in off, and the comment on `onWithoutCodes` in `SecuritySettings.tsx` goes. Tests: the old
   codes stop working, the new ones sign in once each, a session without a recent second factor gets 403
   `step_up_required`, the audit event and the email are written.
