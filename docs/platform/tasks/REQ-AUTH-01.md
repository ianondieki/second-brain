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
   **Backend done** (branch `feat/REQ-AUTH-01-followups-7-8`): `DELETE /api/auth/totp/enrol` as above (204 when a
   setup was pending; 409 `totp_already_enabled` when two-step sign-in is on, checked first under the lock; 409
   `no_pending_enrolment` otherwise; not audited, like the start of setup), and the 15-minute lifetime without a new
   column: the start time is sealed with the secret inside its AES-GCM envelope, and the confirmation clears a secret
   begun over 15 minutes ago (or stored without a start time) and answers 409 `no_pending_enrolment`. Tests:
   `backend/tests/integration/test_auth_totp_setup.py` (follow-up 7 section, both race orders).
   **BLOCKER fixed (P17):** `2494cdf` let the confirmation copy the pending envelope (`"{secret}|{start}"`) into
   `totp_secret_enc`, so every later TOTP code failed to decode (`binascii.Error`; 5 auth tests failed). The
   confirmation now seals the secret alone under a fresh nonce and clears `totp_pending_enc`. Test:
   `test_a_totp_code_passes_a_step_up_after_enrolment` (the stored envelope decrypts to the bare secret; a TOTP-code
   step-up passes; its replay is refused), red before the fix and green after. Also tested: setup cannot start
   again while two-step sign-in is on (`test_setup_cannot_start_again_while_two_step_sign_in_is_on`).
   **Start time in the envelope, not a column** (the Handoff's question for the security-reviewer). Kept in the
   envelope because:
   (a) integrity: AES-256-GCM authenticates the whole plaintext, with the user id as associated data, so without
   `DATA_ENCRYPTION_KEY` nobody can change or extend the start time, keep the secret under another time, or move an
   envelope to another user. A `timestamptz` column could be rewritten by anyone who can write the row. The gain is
   small, since such a writer can already clear `totp_enabled_at`, but the envelope gives up nothing for it;
   (b) atomicity: one column holds the secret and its time, so each writer (start, cancel, confirm, expiry, turn-off)
   sets or clears both at once. With two columns, every writer would have to keep them in step, and a missed one
   would leave a secret with a stale or missing time;
   (c) no schema change: a column needs an Alembic revision (db-migrations only) and a change to `bridge_app`'s
   column-level UPDATE grant on `users`, for no security gain;
   (d) fail closed: an envelope without a start time (written before `2494cdf`) counts as expired and is cleared.
   What it costs: (1) both envelopes share one key and the same associated data, so only their format tells them
   apart (`secret|start` or `secret`). Mixing them up was the BLOCKER. It is now closed by construction: the
   confirmation re-seals the bare secret, sign-in reads only `totp_secret_enc`, the test above decrypts the stored
   active envelope, and an active envelope copied into the pending column has no start time and is refused as
   expired. A distinct associated-data label per kind (for example `b"totp-pending:" + user_id`) would separate them
   cryptographically. It is not needed now: secrets pending at deploy would no longer decrypt, so the confirmation
   would also have to treat such an envelope as expired. It is an option for the security review. (2) SQL cannot see
   the time, so a sweeper would have to decrypt rows. None is planned: an abandoned secret stays encrypted, sign-in
   never reads it, and it is refused after 15 minutes. (3) The time is the app clock (`bridge.clock.utcnow`, not the
   tracker's test clock) in whole seconds. Clock skew between API instances shifts the lifetime by the skew. A start
   time in the future is accepted, so a slow instance never refuses a fresh setup; forging one needs the key.
   **Open (impl-frontend):** Cancel sends DELETE and acts on its answer: 204 or 409 `no_pending_enrolment` (two-step
   sign-in is off and nothing is pending, so a later confirmation cannot turn it on) to the "cancelled" notice; 409
   `totp_already_enabled` to the "on" screen with the codes-not-shown notice; anything else keeps the setup steps with
   the status-unknown notice. The lost-answer tests replace their GET /me mocks. A confirmation answering 409
   `no_pending_enrolment` (setup open for over 15 minutes) sends the person back to the start of setup.
8. Backend (`bridge/auth/`, security-reviewer review), then `/settings/security`: new recovery codes. When the
   confirmation's answer is lost after the commit, the person has two-step sign-in on and recovery codes they never
   saw; a role that requires two-step sign-in cannot turn it off and set it up again, so today it has no way to get
   codes (`THREAT_MODEL.md` §1, "Recovery codes never seen after a lost confirmation"). Add a CSRF-checked route that
   issues ten new recovery codes and replaces the old ones in one step under `lock_user` (like
   `confirm_totp_enrolment`; `check_second_factor` rewrites the remaining hashes under that lock when a code is spent,
   so a race test must show a concurrent step-up cannot restore the old hashes), behind the step-up helper (MFA within 12 h),
   with an `auth.recovery_codes_replaced` audit event and a security-notice email ("New recovery codes were
   created."). Then a "Get new recovery codes" action on the "on" screen; the codes-not-shown notices
   (`security.codesNotShown`, `security.codesNotShownTurnOff`) point at it, the latter no longer sending people to
   turn two-step sign-in off, and the comment on `onWithoutCodes` in `SecuritySettings.tsx` goes. Tests: the old
   codes stop working, the new ones sign in once each, a session without a recent second factor gets 403
   `step_up_required`, the audit event and the email are written.
   **Backend done** (branch `feat/REQ-AUTH-01-followups-7-8`): `POST /api/auth/totp/recovery-codes` (CSRF-checked;
   403 `step_up_required` without a second factor in the last 12 h; 409 `totp_not_enabled` when two-step sign-in is
   off; 429 `too_many_attempts` after 5 a minute for the account from any IP, or `REAUTH_IP_LIMIT` from one client IP,
   like the re-auth checks) returns ten new codes once and replaces the old hashes under `lock_user`; the
   `auth.recovery_codes_replaced` audit event (ids only) and the "New recovery codes were created." security notice
   (`[[COPY-REVIEW]]`). Tests: `test_auth_totp_setup.py` (follow-up 8 section), including both race orders with a
   step-up that spends an old code.
   Added in P17: a cross-site POST answers 403 `csrf_failed` and leaves the hashes alone; a replacement behind a
   committing turn-off answers 409 `totp_not_enabled` with no codes, audit event or notice. That race is what
   `lock_user` guards here. The replacement overwrites the whole hash list, so the two step-up races end the same
   with or without the lock; only the turn-off race tells them apart (mutation-proved).
   **For the security-reviewer:** a stolen session whose second factor is under 12 h old can replace the codes. The
   owner's codes then stop working and the owner gets the notice. The thief's codes pass only the second factor, so
   a later sign-in still needs the password or an emailed link. Asking for the current password too, or a fresher
   second factor, would narrow this; the card asked for the step-up helper only, so it is left as is.
   **Open (impl-frontend):** the "Get new recovery codes" action on the "on" screen (on 403 `step_up_required` it asks
   for an authenticator code, POST /api/auth/step-up, then retries; the codes are shown once, as at setup); the
   codes-not-shown notices point at it, `security.codesNotShownTurnOff` no longer sends people to turn two-step
   sign-in off; the comment on `onWithoutCodes` goes.

**Session-only consents at signup (P17, REQ-PROP-05 open item 1):** signup refuses any purpose decided for one sign-in
(`profiles.consents.SESSION_ONLY`, today `tier2_llm_assistant`), whatever its value, with 422 `consent_session_only`
and the settings API's message, so no `source = "signup"` row of it is written. One check,
`service.refuse_session_only`, runs in `_validate_signup` (email form) and in `identities._check_consents`, which runs
at the OAuth start and again at the callback; a flow sealed before the rule lands on
`/signup?oauth_error=consent_session_only` and creates nothing. The web signup form sends only marketing, reminders,
whatsapp and profiling, so it is unaffected. Tests: `test_signup_refusals_create_no_account_and_send_nothing`,
`test_signup_needs_the_terms_and_current_consents`, `test_a_flow_carrying_a_session_only_consent_creates_nothing`.
Mutations killed: no check on the email path; none on the OAuth path; only granted values refused; the callback
skipping the check.

**Demo seed (merge of `7e813ce`):** the M1 demo seed sealed its fixed TOTP secrets into `totp_pending_enc` itself, as
bare secrets, which follow-up 7 treats as expired (17 demo tests errored with 409 `no_pending_enrolment`).
`service.seal_pending_secret` is now the one writer of the pending envelope; `begin_totp_enrolment` and the seed's
`enrol_totp` both call it.

**P17 backend status (2026-09-29, `feat/REQ-AUTH-01-followups-7-8`):** the BLOCKER is fixed and the integration branch
is merged in (last at `7e813ce`). Full backend suite: 3201 passed. `bridge/auth/service.py`: 99% with branches (93% on
the merged tree before these tests; the Handoff measured 91%). The one line left (283) re-raises when an insert fails
while the address is still free. New tests reach the auth paths nothing tested: signup refusals, a signup that loses
the race for its address, magic links to suspended accounts, rehash at login, the new-password policy, a step-up
without two-step sign-in, the second-factor throttle, a wrong second step. Mutation proofs: 33 mutations, all killed
and all restored. They cover the fix; the lifetime, expiry-clearing and cancel guards of follow-up 7; the lock,
step-up, turn-off check, audit, notice and throttle guards of follow-up 8; the session-only signup rule; and the paths
the new tests reach. Next: security-reviewer (one round) and reviewer on this branch, then the frontend halves
(impl-frontend) with ux-reviewer.
