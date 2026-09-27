# REQ-AUTH-02

- Task: T2.12 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend, impl-frontend (buttons, linked accounts, F4); security-reviewer (Fable)
- Files owned: `bridge/auth/oauth.py`, OAuth routes in `bridge/auth/router.py`, `frontend/app/(public)/login/`, `frontend/app/(app)/settings/security/`
- Depends on: Phase 1 auth. Real sign-in needs the human's test apps (`DECISIONS-NEEDED.md` D-26); CI uses respx fakes.

## Scope

GitHub and Google OAuth 2.0 (authorization code + PKCE S256, `state` and `nonce` in a signed short-lived cookie, exact redirect URIs): sign-in to an existing account by a verified provider email, signup for a new account, and linking from `/settings/security` only inside a signed-in session with a fresh second factor where the account has TOTP. `auth_identities` unique(provider, subject); unlinking needs another sign-in method. Unverified provider emails never log into or link an existing account (pre-hijacking). Client ids and secrets only from `.env` (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`); the buttons hide when unset (fail closed).

## Acceptance criteria and tests

AC-SEC-1/b re-run; `backend/tests/unit/auth/test_oauth.py` and `integration/test_oauth_flows.py` (respx fakes of the token and user-info endpoints).
