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
   expired. Since the security review (P17 round 1) the kinds are also separated cryptographically: the pending
   envelope's associated data is `totp-pending|` and the user id, the active one's the user id alone, and a pending
   envelope that does not open (sealed before the label, under another key, or altered) is cleared and answered like
   an expired one instead of a 500; a secret pending at deploy therefore reads as expired. (2) SQL cannot see
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
   **Proof (security review, P17 round 1):** the step-up alone was not enough, since a recovery code spent at step-up
   also makes the factor fresh. The route now takes `ensure_fresh_proof`, as linking and unlinking a sign-in method
   do: a second factor within 12 h and `current_password` when the account has one (optional JSON body; 403
   `current_password_required`), checked under `lock_user` after 409 `totp_not_enabled`. `ensure_fresh_proof` moved
   from `identities.py` to `service.py` (identities imports service). The notice goes out at most once per account and
   Nairobi day (dedupe key); every replacement is audited.
   **Open (impl-frontend):** the "Get new recovery codes" action on the "on" screen (it sends `current_password` when
   the account has one, as linking does, and 403 `current_password_required` asks for it again; on 403
   `step_up_required` it asks for an authenticator code, POST /api/auth/step-up, then retries; the codes are shown
   once, as at setup); the
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

**Security review round 1 (P17), fixed:** MAJOR: `POST /api/auth/totp/confirm` had no throttle (40 wrong codes in a
minute, no 429), so a stolen session could guess against a setup the owner had begun. It now shares the second
factor's budget (`mfa` keys: 5 codes a minute for the account from one client IP), checked before `lock_user`, each
checked code recorded and kept by the router's commit, the throttled case logged (`auth.totp_confirm_throttled`).
MINORs: a pending envelope that does not open counts as expired, and the pending kind has its own associated-data
label (follow-up 7 above); new recovery codes need `ensure_fresh_proof` and send one notice a day (follow-up 8 above);
`record_decisions` writes a session-only purpose only with a `session:` source (defence in depth); the session-only
refusal message lives in `profiles/consents.py`, imported by both routers. Tests:
`test_the_setup_confirmation_is_throttled_like_the_second_factor`,
`test_the_pending_envelope_opens_only_under_its_own_label`,
`test_a_pending_envelope_that_does_not_open_counts_as_expired`,
`test_new_recovery_codes_need_the_current_password_even_after_a_recovery_code_step_up`,
`test_the_new_recovery_codes_notice_goes_out_once_a_day`, `unit/test_consents.py`
`test_a_session_only_purpose_is_recorded_only_for_a_login_session`. The shared budget means the enrolment's
confirmation counts as one of the five codes of `test_the_second_factor_is_throttled_after_five_attempts`.

**P17 backend status (2026-09-29, `feat/REQ-AUTH-01-followups-7-8`):** the BLOCKER is fixed and the integration branch
is merged in (last at `7e813ce`). Full backend suite: 3214 passed (after security review round 1).
`bridge/auth/service.py`: 99% with branches (93% on the merged tree before these tests; the Handoff measured 91%). The
one line left (286) re-raises when an insert fails while the address is still free. New tests reach the auth paths
nothing tested: signup refusals, a signup that loses the race for its address, magic links to suspended accounts,
rehash at login, the new-password policy, a step-up without two-step sign-in, the second-factor throttle, a wrong
second step. Mutation proofs: 41 mutations, all killed and all restored. They cover the fix; the lifetime,
expiry-clearing and cancel guards of follow-up 7; the lock, step-up, turn-off check, audit, notice and throttle guards
of follow-up 8; the session-only signup rule; the security review round 1 fixes (the confirmation throttle, the
pending label and unopenable envelopes, the recovery-codes proof and daily notice, `record_decisions`); and the paths
the new tests reach. Next: the security-reviewer's check of the round 1 fixes, then the frontend halves
(impl-frontend) with ux-reviewer.

## P17-F: frontend halves of follow-ups 7 and 8 (2026-09-30, `feat/REQ-AUTH-07-fe`)

**Follow-up 7, Cancel setup.** "Cancel setup" always sends `DELETE /api/auth/totp/enrol` (CSRF-checked, 10 s
timeout) and acts on its answer, never on GET /api/auth/me: 204 or 409 `no_pending_enrolment` go to the "cancelled"
notice; 409 `totp_already_enabled` goes to the "on" screen with the codes-not-shown notice; anything else keeps the
setup steps with the status-unknown notice. A confirmation answering 409 `no_pending_enrolment` (replaced, or open
over 15 minutes) settles the same way: back to the start when the DELETE says off. The mapping is
`cancelStatus` in `frontend/app/(app)/settings/security/outcomes.ts`. The lost-answer tests now mock the DELETE instead
of GET /me.

**Follow-up 8, new recovery codes.** The "on" screen has a "Recovery codes" section. Its "Get new recovery codes"
button opens a form that loads on demand (`NewRecoveryCodes.tsx`). The form warns that the old codes stop working,
asks for the current password when the account has one, then sends `POST /api/auth/totp/recovery-codes`:
- 403 `step_up_required` shows the code form (`POST /api/auth/step-up`), then sends again with the password already
  typed.
- 403 `current_password_required` asks for the password again (the field is emptied and focused, and it also appears
  for an account the page thought had no password).
- 409 `totp_not_enabled` goes back to the start with `errors.totp_not_enabled`.
- Any other refusal keeps the form with its `errors.*` message. Unknown codes read `generic`; the API's own
  `message` is never shown.

The ten codes are shown once (`RecoveryCodeList.tsx`, shared with setup), with copy, download and "Your new recovery
codes are ready. Your old codes no longer work." "I have saved my codes" returns focus to the button. While the form
is open, turning off and the Password section step aside. After a lost setup answer, the button is the screen's one
primary action. `security.codesNotShown` points at it for every role. `security.codesNotShownTurnOff` and the
`onWithoutCodes` comment are gone. The mapping is `renewalStep` in `outcomes.ts`.

**Tests.**
- Vitest: `outcomes.test.ts` covers every answer of both routes. `recovery-codes.test.tsx` covers the section and the
  primary rule; the password (empty, wrong, absent); step-up and retry; `totp_not_enabled`; fixed messages for
  throttling, CSRF, 5xx, unknown codes and no connection, where the API's text never appears; busy presses; and copy
  and download. `settings.test.tsx` has the lost-answer cases on the DELETE. Five mutations of the new code were each
  caught.
- Playwright: `frontend/e2e/two-step.spec.ts` runs in mobile-360 and desktop:
  - Cancel clears `totp_pending_enc`, and a code from the cancelled key gets 409 `no_pending_enrolment`.
  - A confirmation whose answer is cut off leads, on Cancel, to "on" with the notice.
  - With a 13-hour-old second factor: password, then a fresh code, then ten new codes; the notice email reaches
    Mailpit; at the next sign-in an old code is refused and a new one signs in.
  - axe, one primary action and no horizontal scroll on each screen, at the project width and at 375 px. A `beforeAll`
    expect requires `E2E_DATABASE_OWNER_URL`.
- `auth.spec.ts` and `smoke.spec.ts` stay green on the same stack.

Screenshots (`E2E_SHOTS_DIR`, 375 and 1440 px): `p17f-cancelled`, `p17f-codes-not-shown`, `p17f-renew-form`,
`p17f-renew-step-up`, `p17f-renew-codes`.

**Open items (P17-F):**
1. **Cancel with an unclear answer, when nothing can be on.** Before any confirmation could have committed (no try
   yet, or only wrong codes), an unclear DELETE answer (offline, 5xx, session ended) shows "cancelled", not the
   status-unknown notice. Two-step sign-in cannot be on, and the server refuses the key after 15 minutes. This
   departs from the literal "anything else keeps the setup steps"; reviewer to confirm.
2. **A DELETE after the confirmation's `no_pending_enrolment` can clear another tab's setup.** That DELETE also clears
   a key a newer setup in another tab left pending; that tab's confirmation then starts again. Safe, but visible.
3. **`THREAT_MODEL.md` rows can now be narrowed.** Three §1 rows ("A pending TOTP secret lingers", "Cancel setup reads
   'off' before a lost confirmation commits", "Recovery codes never seen after a lost confirmation") still say "until
   the web client ...". Their test columns should name `recovery-codes.test.tsx`, `outcomes.test.ts` and
   `e2e/two-step.spec.ts`. The "roles that may turn two-step sign-in off are told to turn it off" clause is now
   stale. Left to the orchestrator or security-reviewer, after review.
4. **The JS budget is close.** Signed in, local production build: `/settings/security` loads 148,601 of 150,000
   bytes of gzipped JS. The new form loads on demand; the section and button are in the first load.
5. **Copy.** New copy is `[[COPY-REVIEW]]` (`_meta.reviewP17f`); the Swahili is a draft (`[[SW-REVIEW]]`).
   `mfa.recoveryLead` now reads "Enter one of the recovery codes you saved." because codes no longer come only from
   setup.
6. **Shared files.** `lib/api/errors.ts` gains one known code (`totp_not_enabled`). This may overlap with parallel
   edits to that list.
7. **Skill not installed.** The `impeccable` skill is not installed here, so the polish pass was a manual review of
   the screenshots against docs/spec/07. At 375 px, "Copy codes" and "Download codes" wrap onto two lines, as at
   setup (no change made).
