# REQ-FND-02

- Task: T1.3 (`docs/platform/PLAN.md` Phase 1)
- Agent: orchestrator (B, F, I)
- Files owned: `backend/` (skeleton), `frontend/` (skeleton), `infra/`, `Makefile`
- Depends on: T1.2.

## Scope

Monorepo scaffold: `backend/` (uv, FastAPI, Pydantic v2, SQLAlchemy 2 async + psycopg 3, Alembic, Procrastinate, structlog; package `bridge`), `frontend/` (Next.js pinned per the ADR-001 addendum, Tailwind, shadcn/ui, next-intl, openapi-typescript), `infra/docker-compose.dev.yml` (Postgres 16 + pgvector, Mailpit, MinIO, ClamAV; api, worker, web), `Makefile` (`make dev`, `make check`), `backend/.env.example`, `frontend/.env.example`.

## Acceptance criteria and tests

AC-SEC-5: `make check` never reaches a provider (socket guard in `backend/tests/conftest.py`; egress-locked CI steps).

## Notes

The app fails closed when a required secret is missing (`bridge/config.py`).

## Prototype P9 `make demo` (basic) (PLAN.md §8; D-36; with REQ-DIR-02; branch `feat/REQ-FND-02-demo`)

Built by impl-backend, 2026-09-29. Files: `infra/docker-compose.demo.yml`, `infra/demo/demo.py`, `Makefile` (demo
targets), `.gitignore`, `backend/src/bridge/seed/demo/` (`data.py`, `runtime.py`, `accounts.py`, `proposals.py`,
`engagements.py`, `__init__.py`), `backend/src/bridge/seed/__main__.py` (`--demo`), `backend/src/bridge/demo/`
(`python -m bridge.demo totp|logins|cert-id|clock`), `.github/workflows/pr.yml` (e2e job), `infra/ci/make-env.sh`,
`frontend/e2e/{verify,proposal-wizard}.spec.ts`, `frontend/e2e/support/verification.ts`, `frontend/.env.example`,
`.gitleaks.toml` (the public demo password), README "Run the demo".

- **Stack.** An override of the dev stack as its own project `bridge-demo` (its volumes only are wiped by
  `make demo-reset`): APP_ENV=dev, `FEATURE_TIER2_ENABLED` and `FEATURE_DEALS_ENABLED` true, the fake scanner and
  embedder, no ClamAV, the dev image (WITH_DEV_TOOLS=true), secrets from the generated `infra/demo/backend.env` over
  `backend/.env` (where the owner puts the LLM variables), the demo seed in the migrate step after the buckets and the
  signing key, SeaweedFS with explicit volume slots (by default it sized them from the free disk and refused uploads
  on a small Docker disk), and `mem_limit` per service (2.75 GiB in all).
- **Launcher.** `infra/demo/demo.py` (standard-library Python 3.9+, so the same commands on Windows, macOS, Linux)
  writes the throwaway secrets once (never overwritten, gitignored), creates `backend/.env` from the example when
  missing, runs compose, prints the URLs and logins; `reset` wipes only with `--yes`, which only `make demo-reset`
  passes. `DEMO_COMPOSE_EXTRA` adds out-of-repo compose files (the build container's CA override, other host ports).
- **Seed** (`python -m bridge.seed --demo`; dev and test only, refused in staging, production and with APP_ENV unset,
  before anything is written). Through the application wherever a path exists: accounts by `create_account` (the
  reminders consent granted), seats added by the organisation's owner under RLS, TOTP confirmed by
  `POST /api/auth/totp/confirm` on a secret derived from the address, D1 through the phone routes and the fake SMS
  provider, the signatory's Master Enterprise Terms under RLS, drafts, publishing (the T2.4 registration queued), the
  Pitch (P4 hooks and P5's `open_engagement_for_tag`), the Evaluation NDA and one Tier-2 view, and the engagements
  through the tracker API with every party signed in by `POST /api/auth/login` and `/api/auth/mfa/verify` (the
  ADR-002 step-up). As the owner role, where no path exists yet: `users.demo_account`, D2, the fixtures' E1/E2 level,
  domain, county and niche, the E0 fixture. Idempotent and resumable; a database seeded under another
  `DATA_ENCRYPTION_KEY` is refused with a pointer to `make demo-reset`.
- **Data.** Amina (D2) and Brian (D1); Telco A (fixture) and SACCO B (fixture), E2 with owner/admin, signatory,
  reviewer and finance seats; County Government of C (fixture), E1; NGO D (fixture), E0. P1..P4 published with
  certificates, three new problems and one linked; tags delivered to E2 and held for E1/E0; engagements SUBMITTED
  (P3, Telco A), INTEREST_CONFIRMED (P4, SACCO B; EM2), NEGOTIATION (P1, SACCO B) and CLOSED (P2, Telco A: both
  signatures on the NDA, agreement and certificate behind TOTP, two milestones, a recorded and confirmed payment).
- **Helpers.** `make demo-totp [EMAIL=]`, `demo-logins`, `demo-clock DAYS= HOURS=` (through `app_set_test_clock`),
  `demo-reminders` (P6's `python -m bridge.reminders run --now` in the worker), `demo-stats`, `demo-logs`;
  `python infra/demo/demo.py e2e-env`.
- **CI (M1 exit, re-check #38).** The e2e job runs the demo seed after the egress lock, waits for the exported
  certificate to be signed (`python -m bridge.demo cert-id --wait`), exports `E2E_VERIFY_CERT_ID` and
  `E2E_DATABASE_OWNER_URL` (password masked) and validates the demo compose file; `make-env.sh` turns both flags on.
  The skips in `verify.spec.ts` and `proposal-wizard.spec.ts` are gone (the tests now require the variables).
- **Demo TSA.** `make demo` timestamps with the configured public TSAs: DigiCert (FreeTSA fallback), free, no
  account. Checked in the build container: the worker's `POST http://timestamp.digicert.com` answered 200 and all four
  records reached `timestamped` with DigiCert serials. So nothing is simulated and no "demo timestamp authority"
  label is needed; offline, records read "Timestamp pending" until reached; `TSA_CA_BUNDLE` is empty in dev, so the
  chain is not pinned (logged). The local openssl TSA exists only in the test suite (`tests/openssl_tsa.py`).

Tests: `backend/tests/integration/demo/test_demo_seed.py` (own database; the flags off then on, then idempotency;
refusals write nothing; demo flags, reminders consent and TOTP; helper codes verify against the stored secrets; D1/D2;
fixture levels, seats, terms; certificates, problems, the exported certificate hashed, signed and timestamped by the
real T2.4 steps with a local test TSA; tags, grants, EM1; engagement stages, chain, signatures, payment, EM2 queued;
the Tier-2 view; the clock helper), `backend/tests/unit/demo/test_demo_policy.py` (policy, CLI refusals, TOTP
derivation, dataset), `backend/tests/unit/ci/test_demo_compose.py` (override, secrets accepted by the app's settings,
gitignore, reset guard, helpers, CI step order and exports, `docker compose config` on the merged file).

Verified end to end in the build container (with an out-of-repo CA override and other host ports): `make demo` built,
seeded and came up healthy in 1 min 52 s from cold images (47 s for `make demo-reset` with cached images); memory in
use once seeded about 420 MiB (API 131, worker 104, S3 66, Postgres 65, web 40, Mailpit 11; the seed peaked at 153
MiB); the whole Playwright suite (60 tests, both projects) passed against it with the two variables from
`demo.py e2e-env`; `make demo-clock DAYS=1` then `make demo-reminders` put the next day's EM7 nudges in Mailpit.

Deviations: commits of the seed runtime/accounts and of the launcher are 300 to 540 lines (one concern each); the
engagements commit also changed how parties sign in (the step-up needs it).

Follow-ups (not built): the image build itself is not measured against 4 GB (BuildKit, outside `docker stats`); the
dev compose file keeps SeaweedFS's default volume sizing (the same small-disk failure can hit `make dev`); a
`[[COPY-REVIEW]]` pass on the fixture proposal texts before recorded demos.
