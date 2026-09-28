# REQ-AUTH-02

- Task: T2.12 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (buttons, linked accounts, F4); security-reviewer (Fable)
- Files owned: `bridge/auth/oauth.py`, OAuth routes in `bridge/auth/router.py`, `frontend/app/(public)/login/`, `frontend/app/(app)/settings/security/`
- Depends on: Phase 1 auth. Real sign-in needs the human's test apps (`DECISIONS-NEEDED.md` D-26); CI uses respx fakes.

## Scope

GitHub and Google OAuth 2.0 (authorization code + PKCE S256, `state` and `nonce` in a signed short-lived cookie, exact redirect URIs): sign-in to an existing account by a verified provider email, signup for a new account, and linking from `/settings/security` only inside a signed-in session with a fresh second factor where the account has TOTP. `auth_identities` unique(provider, subject); unlinking needs another sign-in method. Unverified provider emails never sign in to, create, or get matched to an existing account (pre-hijacking by address); an explicit link from settings by the signed-in user does not depend on the provider address. Client ids and secrets only from `.env` (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`); the buttons hide when unset (fail closed).

## Acceptance criteria and tests

AC-SEC-1/b re-run; `backend/tests/unit/auth/test_oauth.py` and `integration/test_oauth_flows.py` (respx fakes of the token and user-info endpoints).

## Notes

Fix round 1 (reviewer and security-reviewer CHANGES_REQUIRED), orchestrator decisions:

- Sign-in by a verified provider email (the `login`/`signup` intents that match an existing account) does not persist
  an `auth_identities` row. It signs the person in as a magic link would (TOTP accounts land `mfa_pending`) and
  nothing is attached. An identity is attached only when the OAuth flow creates a brand-new account, or through the
  explicit link flow from `/settings/security` inside a signed-in session with fresh proof. The "was added to your
  account" notice and the `auth.identity_linked` audit event happen only in those two cases. An account that already
  holds another identity from the same provider is still refused (`provider_already_linked`) when reached by address.
- The Scope sentence on unverified provider emails is narrowed to address-based matching (pre-hijacking), as above:
  an orchestrator-approved clarification, not a spec change.
- Other fixes: linking and unlinking need the current password on accounts with one (Phase 1 re-auth check,
  throttled), a fresh second factor on TOTP accounts and a recent sign-in otherwise; unlinking ends the account's
  other sessions; OAuth start and callback are throttled to 10 a minute per client IP each; the callback spends its
  `state` server-side on first use (the `login_attempts` ledger, no new table) and releases its database connection
  before the provider call; uvicorn's access log drops the query string on `/api/auth/oauth/*`.
