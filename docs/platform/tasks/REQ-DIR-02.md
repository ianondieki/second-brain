# REQ-DIR-02

- Task: T2.6a (`docs/platform/PLAN.md` Phase 2)
- Agent: researcher (sources), impl-backend (loader)
- Files owned: `backend/seed/ke_provisional.yaml`, `docs/platform/research/phase2-directory-sources.md`, `bridge/seed/directory.py`
- Depends on: T2.1.

## Scope

Provisional directory seed from public registers only (D-21): wedge niches (Microfinance & SACCOs, education, public sector, Social/NGO), telecom licensees (Safaricom, Airtel Kenya, Telkom Kenya, ISPs) and the 47 county governments; each row: legal name, kind, niche slug(s), county, `official_domains[]`, source URL and retrieval date; no personal names, emails, phone numbers or logos. All rows are E0 (`unclaimed`). Loadable only when `APP_ENV in (dev, test)`; the loader refuses otherwise and refuses any verification above `unclaimed` outside test/staging. Badge copy: "Listed from public information · not on the platform · not affiliated" (E0), "Domain verified (pending legal verification)" (E1). G6 approves the production list.

## Acceptance criteria and tests

AC-DIR-3 (`unit/directory/test_seed_policy.py`, `frontend/e2e/directory.spec.ts`), AC-DIR-6 (Safaricom, Airtel and Telkom under ICT › Networks & Telecommunications).
