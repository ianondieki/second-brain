# REQ-DIR-02

- Task: T2.6a (`docs/platform/PLAN.md` Phase 2)
- Agent: researcher (sources), impl-backend (loader)
- Files owned: `backend/seed/ke_provisional.yaml`, `docs/platform/research/phase2-directory-sources.md`, `bridge/seed/directory.py`
- Depends on: T2.1.

## Scope

Provisional directory seed from public registers only (D-21): wedge niches (Microfinance & SACCOs, education, public sector, Social/NGO), telecom licensees (Safaricom, Airtel Kenya, Telkom Kenya, ISPs) and the 47 county governments; each row: legal name, kind, niche slug(s), county, `official_domains[]`, source URL and retrieval date; no personal names, emails, phone numbers or logos. All rows are E0 (`unclaimed`). Loadable only when `APP_ENV in (dev, test)`; the loader refuses otherwise and refuses any verification above `unclaimed` outside test/staging. Badge copy: "Listed from public information · not on the platform · not affiliated" (E0), "Domain verified (pending legal verification)" (E1). G6 approves the production list.

## Acceptance criteria and tests

AC-DIR-3 (`unit/directory/test_seed_policy.py`, `frontend/e2e/directory.spec.ts`), AC-DIR-6 (Safaricom, Airtel and Telkom under ICT › Networks & Telecommunications).

## Notes (T2.6a loader, branch `feat/REQ-DIR-02-provisional-seed`)

- Loader: `bridge/seed/directory.py` (REQUIREMENTS names `bridge/seed.py`; the seed is a package since Phase 1).
  `python -m bridge.seed` loads it after the reference data when `APP_ENV` is dev or test and prints why it skipped
  it otherwise; `seed_directory()` itself raises `DirectorySeedRefused` there. `APP_ENV` must be set explicitly
  (environment or `backend/.env`): the settings default is dev, so an unset `APP_ENV` is refused too. A row may carry an
  optional `verification` (fixture organisations) only with `APP_ENV` test or staging; the provisional file has none.
- Validation before any write: documented fields only (a `logo` or `email` field fails the file), known niche slugs,
  ISO 3166-2:KE county codes (`organizations.county_code` references `regions.code`; First-Schedule numbers are
  refused), https source URLs, unquoted dates not in the future, bare lowercase non-free-mail domains, one organisation
  per domain, unique slugs.
- Upsert keyed by `slug`, refreshed (niches included) only while the row is still a seed organisation at E0 and not
  delisted; claimed, self-signed-up and delisted organisations are left alone, delisting and opt-outs are never
  undone, rows removed from the file stay (tags may point at them). The file holds 85 rows (no basic-education rows:
  no official list, see the research note).
- Safaricom PLC and Airtel Networks Kenya Limited ship with `official_domains: []`: their domains were cited only to
  Wikipedia and await an official citation before G6 (research note, open question 10); E1 by domain match stays
  manual for them until then.
