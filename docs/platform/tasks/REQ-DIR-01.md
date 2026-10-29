# REQ-DIR-01

- Task: T2.6a (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend (API, seed), impl-frontend (Companies, F1)
- Files owned: `bridge/directory/{service,router,schemas}.py`, `bridge/seed/`, `frontend/app/(app)/dev/companies/`
- Depends on: T2.1.

## Scope

Niche taxonomy (two-level, ISIC-mapped, seeded in Phase 1) and org types; an admin can add a niche without a deploy (staff route) and it becomes selectable in the directory and the editor at once. Directory API and screen grouped by niche headings with org-type and county filters; cards show name, niche, org type, county and the verification badge, never a logo; the responsiveness score shows only for E2 with ≥10 eligible tags and 60 days after the claim (rules in code; values from fixtures until Phase 3).

## Acceptance criteria and tests

AC-DIR-5/a, AC-DIR-6 (`integration/directory/test_seed_and_browse.py`). AC-DIR-5/b is Phase 4.

## Notes (T2.6a backend, branch `feat/REQ-DIR-02-provisional-seed`)

- Routes: `GET /api/directory/orgs` (groups under `Parent › Child` headings; repeatable `kind`, `county` (ISO
  3166-2:KE), `niche` (a parent slug includes its children) filters, at most 50 values each; `q` name search; keyset
  `cursor` over (heading, organisation) pairs, `limit` ≤ 100), `GET /api/directory/orgs/{org_id}` (404 for unknown,
  unlisted or delisted ids), `GET /api/directory/niches` (active niches, two levels, labels, ISIC codes) and
  `GET /api/directory/filter-options` (org types with their docs/spec/03 labels, the 47 counties). Signed-in only.
- Listed = `unclaimed`/`e1`/`e2` and not delisted; the queries repeat the RLS rule, so a member never sees their own
  pending or delisted organisation in the directory. Organisations without a niche come last under a null heading.
  Inactive niches are left out of the picker; organisations keep showing under them until re-tagged.
- Badge copy: E0 and E1 exact from docs/spec/06 6.2. **E2 has no spec copy**: "Legal entity verified", tagged
  `[[COPY-REVIEW]]` in `bridge/directory/service.py`.
- Responsiveness: rules in `bridge/directory/responsiveness.py` (new file): E2, ≥ 10 eligible tags and ≥ 60 days after
  `organizations.e2_verified_at` (read as "after the claim" reached E2). Numbers from a `ResponsivenessSource` on
  `app.state.responsiveness`: none until Phase 3, `FixtureResponsiveness` in tests. The tag count is never exposed.
- Admin niche route: `POST /api/admin/niches` (staff admin; REQ-ADM-01 router) calls `app_add_niche` (schema v2 fix
  round); 201 with the niche, 409 `niche_slug_taken`, 422 `parent_niche_not_top_level` / `parent_niche_not_found`,
  audited `directory.niche_added` (ids only). `test_an_admin_added_niche_is_selectable_at_once` proves AC-DIR-5/a end
  to end through the route; `integration/admin/test_add_niche.py` covers the refusals.
- `backend/pyproject.toml`: ruff `allowed-confusables = ["›"]` (the niche separator).

## Notes (P8 frontend, branch `feat/REQ-DIR-01-screens`)

Built (F1, developer):

- `/dev/companies`: rendered on the server from `GET /api/directory/orgs`, `/niches` and `/filter-options`.
  Organisations under niche headings (parent over child; unsorted last); each row has the name (link), org type and
  county, and the API's badge copy verbatim as its one chip (E2 check, E1 info, E0 dashed ring; D-31 placeholder text
  for E2), never a logo; the response record only when the API sends one. Name search and "Show companies" (the one
  primary action) stay in view; niche, org type and county sit in a disclosure (open when one is set). All a GET form,
  so it works before JavaScript. Keyset paging (30 a page) keeps the filters. Empty, no-match and stale-cursor states
  are one sentence and one action. Developers only (others go to their home).
- `/dev/companies/{org_id}`: badge, org type, county, every niche, response record; unknown, unlisted and delisted ids
  read as not listed. Organisation links and "All companies" carry the list's search, filters and page.
- Developer navigation (`components/DevNav.tsx`): the built sections only (Home, Companies), bottom tabs under
  1024 px and a left rail above, `aria-current` plus colour, weight and a bar. Each later screen adds its row.
- Files: `frontend/app/(app)/dev/companies/` (pages, `directory.ts`, `filters.ts`, `DirectoryFilters`,
  `DirectoryResults`, `OrgRow`, `VerificationBadge`, tests), `frontend/components/DevNav.tsx` (+ test),
  `frontend/e2e/companies.spec.ts`, `frontend/e2e/support/accounts.ts`. Copy `nav.*`, `companies.*` is
  `[[COPY-REVIEW]]` (`_meta.reviewP8`); Swahili drafts `[[SW-REVIEW]]`.

Shared files changed: `frontend/components/SignedInShell.tsx` (optional `nav` and `wide`; room for the fixed tab
bar), `frontend/app/globals.css` (focus scrolling clears the tab bar), `frontend/components/ui/icons.tsx` (Home,
Companies, Listed, Chevron), `frontend/app/(app)/dev/page.tsx` (shows the nav), `frontend/lib/api/server.ts`
(`forwardHeaders()`, see REQ-PROV-02).

Follow-ups, not built:

- The organisation page is a dead end: "Pitch to company" arrives with P4 (directory search + Pitch).
- Paging shows neither position nor a total (the API returns a cursor only); add "page n" or a count if the API
  grows one.
- JS budget: `/dev/companies` measures about 145 KB gzipped of 150 KB; add the Lighthouse CI budget (AC-UX-3) before
  the next screen.
- Org-type labels come from the `orgKind` locale keys; niche and county names are the API's data, untranslated.
- THREAT_MODEL note on X-Forwarded-For: see REQ-PROV-02.
