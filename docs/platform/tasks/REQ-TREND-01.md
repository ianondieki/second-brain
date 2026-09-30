# REQ-TREND-01 (with REQ-TREND-02 backend and REQ-PERS-01, prototype part)

- Task: P12-B Trending and the ranker, backend (`docs/platform/PLAN.md` §8, prototype track M2;
  `docs/platform/prototype-m2-plan.md` §1 P12 row, §3 P12 bullet, §6). The screens (`/dev/discover`, Home
  "Recommended for you", the liked-niches picker, Discover in DevNav) are P12-F.
- Agent: impl-backend. Reviews: reviewer. No security-reviewer (plan §5: P12-B writes no Tier-2 view signal and
  writes no signal at all; it reads `app_trend_aggregates`, whose owner is D-46's).
- Branch `feat/REQ-TREND-01-trending` from integration `84e0af0` (0005, P10, P11, P13, P14 merged).
- Depends on: revision 0005 (`app_trend_aggregates`, D-46), `signal_events` and `developer_niches` (0001),
  `profiling` consent (0001, `consents.yaml`), P10 (`scout_match`, `org_interest` signals), P11 (approved research
  cards), P9 (demo seed). No schema change, no new environment variable, no model call, no new dependency.

## Files

| Area | Files |
|---|---|
| Numbers | `backend/config/ranking/weights_v1.yaml`; loader `bridge/matching/ranking_config.py` (fails closed) |
| Trends | `bridge/matching/trending.py` (pure: decay, niche z-scores, anti-gaming), `bridge/matching/trend_facts.py` (facts under RLS, aggregates through the definer, the board) |
| Discover | `bridge/matching/discover.py`, `bridge/matching/discover_schemas.py` |
| Ranker | `bridge/matching/ranker.py` (pure), `bridge/matching/recommendations.py` (developer context, response) |
| Liked niches | `bridge/profiles/niches.py` |
| Routes | `bridge/matching/router.py` (one router; one import and one `include_router` line in `main.py`) |
| Demo seed | `bridge/seed/demo/trending.py`; one import and one step in `bridge/seed/demo/__init__.py` |
| Generated | `backend/openapi.json`, `frontend/lib/api/schema.d.ts` (openapi-typescript 7.13.0) |
| Tests | `tests/unit/matching/test_{ranking_config,trending,ranker}.py`; `tests/integration/matching/{trend_world,test_discover,test_opportunity_gap,test_badge_privacy,test_recommendations,test_liked_niches,test_trends_perf}.py`; one test and two tables in `tests/integration/demo/test_demo_seed.py` |

## What it does

**Signals.** Nothing new is written. `proposal_published` and `proposal_version_published` are already written by
the publish path and by a moderator's approval of a held proposal (P2, `proposals/service.py` `signal`; asserted by
`integration/proposals/test_publish.py`), P10 writes `scout_match` and `org_interest` (`tenancy/signals.py`). The
publication kinds have one actor each and never pass the definer's 3-actor floor, so, as the 0005 card says,
publication facts come from `proposals.published_at` and the problem links, read under RLS.

**Trends** (`trending.py`, `trend_facts.py`), computed on each request, nothing stored:

- Facts: published, clear problems (a Brief only when its `problem_briefs` row is published and visible), their
  sources' publisher and date, published, clear proposals and the problems their current version links, and
  `SELECT … FROM app_trend_aggregates(since, now)` for `scout_match` and `org_interest` only. `since` is a Nairobi
  day boundary 180 days back and `now` is `app_clock_now()`: the window is never a caller's value (the bisection
  concern of the 0005 re-check cannot be driven through these routes).
- Problem events (weights from the YAML, docs/spec/06 6.6): verified-org Brief 6, official source 5, independent
  source 3, proposal submitted 2 (once per developer and day; never the problem's own creator), scout match 2
  (the day's highest count across the linked proposals). Project events: organisation interest 12. Half-lives 14
  and 7 days; ages in whole Africa/Nairobi days; facts older than the window count for nothing.
- z-score per niche: every item of the niche scored at weekly points over 90 days (an item from its publication or
  its first dated event, whichever is earlier), mean and population sd (floor 0.5). Fewer than 3 non-zero baseline
  scores: no z-score (cold start). Trending = z >= 1.0, score >= 1.0, >= 3 distinct actors (proposal owners,
  source publishers, the Brief's organisation, the scouting organisations). New this week = published in the last
  7 Nairobi days.
- Anti-gaming: see "Anti-gaming coverage" below.

**Discover** (`discover.py`):

- Trending Problems: Trending or New this week, Trending first (by z, then score), at most 20; each with its 3
  newest sources, its Why chips (at most 3: new sources this month, companies scouting, new proposals this month,
  verified-organisation Brief, New this week) and a badge only when Trending: `Trending in <niche label> · <county or
  country>: <two facts>`, e.g. `Trending in ICT › Networks & Telecommunications · Kenya: 4 companies scouting`.
  Organisations are counted only from 3 and never named.
- Trending Projects: Trending (organisation interest) or New this week, each with the visible problem it solves
  (the one trending most); a proposal whose problems are all hidden is not listed. Their badge is `Trending in
  <niche>` and their chips never count organisations; their score and z are not returned (a score counts them).
- Opportunity Gap: problems with a z-score and a positive score, ranked by z; the top `ceil(10 %)`; of those, the
  ones with fewer than 3 published proposals.
- Filters: `niche` (slug; a parent includes its children; unknown: empty) and `county` (exact code). Baselines are
  the platform's whatever the filter.

**Ranker** (`ranker.py`, `recommendations.py`), no model (the plan names none for P12):

- Items: approved research cards and verified organisations' published Briefs only (AC-PERS-7).
- Features f1-f10 in [0, 1], `score = 100·Σw·f/Σ|w|` over the features that apply, +5 for a card published in the
  last 7 days. f1 = shared keywords with the developer's headline, bio and last 5 published proposals (Tier 1),
  saturating at 5 (no embeddings in the prototype); f2 liked 1 / adjacent (sibling, parent or child) 0.5; f3 same
  county 1 / nationwide 0.5 / else 0 (applies when the developer gave a county); f4 never applies (no skills data);
  f5 the card's z clipped to ±3 (applies with a z); f6 the card's confidence, 1.0 for a Brief; f7
  `log(1 + scouting orgs + Briefs)`, cap 10; f8 `log(1 + proposals)`, cap 20, weight −0.07; f9 `(done+1)/(started+2)`
  in the card's niche (published proposals started, CLOSED engagements done); f10 `2^(−age/30)`.
- Profiling consent (default off): without it f1 and f9 never apply and neither the proposals nor the engagements
  are read; the liked niches and the county the developer gave (onboarding's stated preferences) and public facts
  rank. No profile embedding is ever computed in the prototype.
- MMR λ 0.7 (similarity 1 same niche, 0.5 same family), at most 3 per niche in the top 10, one exploration slot
  (the best card outside the liked and adjacent niches, last, `exploring: true`) when the developer has liked niches.
- Labels Strong fit >= 80, Good fit >= 60, Stretch. Pursuit: Not now when >= 10 proposals and no market pull, or a
  score < 40, or confidence < 0.5; Pursue when score >= 60, confidence >= 0.6, market pull or z >= 1, and not crowded;
  else Consider; always with reasons. Why chips: the top 3 positive contributions whose fact holds; Why-not: the
  proposal count, else "Outside your liked niches", else thin evidence. No revenue or profit wording anywhere.

**Liked niches** (`profiles/niches.py`): PUT sets the whole list, 3 to 5 active niche ids (YAML), duplicates once;
followed niches untouched; RLS keeps each user to their own rows. 404 without a developer profile.

**Demo seed** (`seed/demo/trending.py`, after the engagements and research cards): liked niches for Amina
(Microfinance, Networks & telecommunications, Agriculture) and Brian (County government, Microfinance, Health)
through `PUT /api/me/niches`; Amina's profiling consent through `PUT /api/me/consents` (Brian keeps the default);
simulated `scout_match` / `org_interest` signals written by the owner role from pseudonyms of no account (the demo
has two E2 fixtures; trends need three organisations): weekly history, then a burst for P2 and P1 this week. Signal
ids are uuid5 of the Nairobi ISO week, proposal, kind, organisation and day: a second run in the same week inserts
nothing, a later week tops the demo up. Choices made in the app (niches set, consent decided) are kept.

## API for P12-F

All require a session; errors are the usual `{detail: {code, message}}`.

- `GET /api/discover/trending?niche=<slug>&county=<KE-nn>` → `TrendingOut`:
  `{generated_at, problems: TrendingProblem[], projects: TrendingProject[]}`.
  - `TrendingProblem`: `{problem: DiscoverProblem, trend: TrendOut, why: string[] (≤3), sources: DiscoverSource[]
    (≤3), proposal_count, project_ids: uuid[] (≤3, ids in projects)}`.
  - `DiscoverProblem`: `ProblemRef` (`id, title, source, label, niche {id, slug, label}`) + `statement, country,
    county_code, published_at`.
  - `TrendOut`: `{trending, new_this_week, z (null in cold start), score, badge (null unless trending)}`.
  - `DiscoverSource`: `{url, publisher, source_type, published_date, retrieved_at, quote}`.
  - `TrendingProject`: `{proposal: TeaserItem (as Browse), problem: ProblemRef (always), trend: ProjectTrendOut
    {trending, new_this_week, badge}, why: string[]}`.
- `GET /api/discover/opportunity-gap?niche=&county=` → `{generated_at, items: TrendingProblem[]}` (`project_ids`
  empty).
- `GET /api/me/recommendations` → `RecommendationsOut`: `{generated_at, ranker_version, personalised,
  liked_niches: NicheOut[], items: Recommendation[]}`; `Recommendation`: `{problem: DiscoverProblem, position, score
  (0-100), label ("Strong fit" | "Good fit" | "Stretch"), exploring, pursuit {decision ("pursue" | "consider" |
  "not_now"), label ("Pursue" | "Consider" | "Not now"), reasons: string[] (≥1)}, why: string[] (≥1), why_not,
  trend: TrendOut, features: {semantic_fit … freshness: {raw, value, weight, applies}}}`. 404 without a developer
  profile. An empty `items` is the empty state (no cards yet).
- `GET /api/me/niches` → `{liked: NicheOut[], min: 3, max: 5}`; `PUT /api/me/niches` body `{liked: uuid[]}` (ids
  from `GET /api/directory/niches`) → the same; 422 `liked_niches_count` or `unknown_niche` (with `niches`); 404
  without a developer profile.
- The profiling toggle is the existing `PUT /api/me/consents` (`profiling`).
- Copy: every chip, badge and reason is code-written `[[COPY-REVIEW]]`.

## Acceptance tests

| AC / rule | Test |
|---|---|
| AC-TREND-1 five saves by one account in one day count as one | `unit/matching/test_trending.py::test_anti_gaming` (code) and 0005's `integration/matching/test_trend_aggregates.py::test_events_count_each_actor_once_per_item_and_day` (definer) |
| AC-TREND-1 young-account cohort > 50 % excluded | `unit/matching/test_trending.py::test_anti_gaming` (the rule); **no data yet**, see "Needs a revision" |
| AC-TREND-2 every Trending Project card renders its linked problem | `integration/matching/test_discover.py::test_a_rising_problem_trends_with_its_badge_sources_and_project_beside_it` (backend half; `frontend/e2e/discover.spec.ts` is P12-F) |
| AC-TREND-2 Opportunity Gap only < 3 proposals | `integration/matching/test_opportunity_gap.py` |
| AC-TREND-3 50k events, twice, idempotent, < 5 min | `integration/matching/test_trends_perf.py` (own database; slowest request 0.9 s; bound 60 s) |
| AC-REPO-6/b trending badges never name tagged organisations | `integration/matching/test_badge_privacy.py::test_trending_badges_never_name_the_tagged_organisations` |
| AC-PERS-1 new developer, 3 liked niches, a county: explained list | `integration/matching/test_recommendations.py::test_a_brand_new_developer_gets_an_explained_list`, `unit/…/test_ranker.py::test_a_brand_new_developer_gets_an_explained_list` |
| AC-PERS-2 (backend) feature vector, pursuit chip, ≥1 Why chip, no profit wording, crowded never Pursue | `unit/matching/test_ranker.py` (`test_every_row_…`, `test_a_crowded_card_…`, `test_nothing_mentions_profit_or_revenue`); the 360 px render is P12-F |
| AC-PERS-3 (prototype) opt-out removes f1 and f9, no profile embedding | `integration/matching/test_recommendations.py::test_turning_profiling_off_removes_f1_and_f9`, `unit/…/test_ranker.py::test_profiling_consent_gates_f1_and_f9` |
| AC-PERS-7 only approved cards and Briefs; f5 = the card's z, f6 = its confidence; no candidate | `integration/matching/test_recommendations.py::test_only_approved_cards_and_briefs_with_their_z_score_and_confidence` |
| Tier 2 never enters Discover or recommendations | `integration/matching/test_badge_privacy.py::test_no_tier2_text_reaches_discover_or_recommendations`; P10's import lint covers every new `bridge/matching` module |
| Anti-gaming: self-boost, same-organisation, 3 actors, cold start | `integration/matching/test_discover.py` (two tests), `unit/matching/test_trending.py` |
| Liked niches API | `integration/matching/test_liked_niches.py` |
| Demo seed | `integration/demo/test_demo_seed.py::test_discover_and_recommendations_have_something_to_show`, and the idempotency test now counts `signal_events` and `developer_niches` |

Out of scope here (REQ-PERS-02, REQ-PERS-04): AC-PERS-4 (G-EVAL set), AC-PERS-5 (LambdaMART), AC-PERS-6 (GitHub
import; f9 from the platform is built, its pair-2 test is REQ-PERS-02's).

## Anti-gaming coverage (docs/spec/06 6.6)

| Rule | Where |
|---|---|
| Unique verified accounts | structural: `org_interest` needs an E2 signatory, `scout_match` an E1/E2 scout, a proposal a D1 developer |
| 1 event / account / item / day | the definer (org-side kinds); `once_per_actor_and_day` (proposals against a problem) |
| No self boosts | a problem's creator's proposals never count for it |
| No same-org boosts | an org-side kind counts only from 3 distinct organisations, weighted by organisations per actor |
| ≥ 3 distinct actors | the definer per item and kind; `min_actors` per item before Trending |
| Burst detector | the rule is code (`without_bursts`) with no data source yet |
| Wilson lower bound | not built: no ratio feature in the prototype |

## Needs a revision (0006, db-migrations; not built, reported)

1. **Burst detector data (AC-TREND-1, second half).** `app_trend_aggregates` must also return, per item, kind and
   day, the events whose actor's account is younger than 7 days (`young`; never ids), computed inside the definer
   from `users.created_at` of the account behind the actor digest. The signal row holds only a salted digest, so
   the definer needs a way from digest to account age: either a `signal_events.actor_created_on date` column written
   with the signal (the simplest; the writer knows its own account) or a join through `app_subject_digest` for the
   window's actors. `without_bursts` then applies as it is (`Aggregate.young`).
2. **Self-boost through an organisation the developer belongs to.** A developer who is a member of an organisation
   can express that organisation's interest in their own proposal. The definer would have to drop an org-side signal
   whose actor digest equals the proposal owner's digest (the salt never leaves the database).
3. From the 0005 re-check, still open: snap `p_since`/`p_now` to Nairobi day boundaries inside the definer (the
   routes already pass day-boundary `since` values), a `published_date` floor, abandoning a stuck research run.
   Nothing here needs `budget_band` on proposals.

## Deviations (prototype)

- Computed on read: no `trends.recompute` (02:00) or `recommendations.recompute` (03:00) jobs, no stored scores or
  recommendation rows (0005's "not in 0005" list); each recommendation returns its feature vector instead (AC-PERS-2
  "stores" is the response).
- f1 is keyword overlap, not bge-m3; f4 never applies; tenders and developer saves have no data; shortlist and
  verified-view project signals do not exist (a Tier-2 view signal would need the security-reviewer).
- County is treated as a stated preference (onboarding) and ranks without the profiling consent, like the liked
  niches; the consent text says "Use my niches and activity …" (see open item 2).
- Impressions, outcomes and thumbs (docs/spec/06 6.7 logging) are REQ-PERS-04 and not built.
- The EM7 trending line flag (REQ-TREND-02's `reminders/dispatch.py` part) is not touched.

## Open items

1. **Definer performance without statistics.** On a freshly bulk-loaded `signal_events` (50k rows, no ANALYZE) the
   first `app_trend_aggregates` call took about 150 s; after `ANALYZE signal_events`, 0.2 s. Autovacuum analyses a
   table that grows like this, and the perf test runs ANALYZE the way it would. db-migrations may want to look at the
   definer's plan (an index serving its grouping) in 0006.
2. **Consent wording vs. behaviour.** The `profiling` text reads "Use my niches and activity to recommend …", while the
   ranker uses liked niches and county without it (as the task asked: "without it, rank on liked niches and public
   facts only"). Either the wording changes (a new consent text version, `[[COPY-REVIEW]]`) or niches and county
   also wait for the consent. Decision for the orchestrator.
3. Liked niches must be 3 to 5 (REQ-PERS-03): there is no way to clear them; the P12-F picker should say so.
4. The trend of a problem is computed from the whole platform, so a request reads every visible problem and proposal
   and every aggregate row; fine for the prototype (0.9 s at 50k events), a stored recompute at Phase 5.
5. Demo signals are simulated (pseudonyms of no account); README's "real vs simulated" table (P16) should list
   Discover's numbers as simulated.

## Mutation sample

A scratch script (session scratchpad, not committed) applied 15 mutations one at a time and ran the tests named for
each: 15 killed, 0 survived. M1 one event per actor and day (`test_anti_gaming`), M2 burst share
(`test_anti_gaming`), M3 same-organisation floor (`test_one_organisations_seats_count_for_nothing`), M4 self-boost
(`test_the_authors_own_proposals_never_boost_their_problem`), M5 3 actors before Trending, M6 gap "< 3", M7 top
decile (`test_opportunity_gap.py`), M8 crowded never Pursue, M9 consent gating of f1, M10 the consent read
(`test_turning_profiling_off_removes_f1_and_f9`), M11 recommendable sources (AC-PERS-7 test), M12 a count in the
project badge (the Discover test), M13 county filter, M14 liked-niches count, M15 cold start without a baseline.

## Checks (head of the branch)

- `ruff check .`, `ruff format --check .` (535 files), `mypy` (strict, 537 files): clean.
- `python -m bridge.openapi --check`: clean after regeneration; `frontend/lib/api/schema.d.ts` regenerated with
  openapi-typescript 7.13.0 (the same version reproduces the base branch's file byte for byte). No existing schema
  name changed (the first cut's `SourceOut` clashed with the admin research one and was renamed `DiscoverSource`).
- Backend suite: 3917 passed (13 min). New: 131 unit tests in `tests/unit/matching` (45 new), 13 integration tests,
  1 perf test (own database), 1 demo-seed test.
- `scripts/copy_lint.py`: PASS. `docs/platform/checks/check_traceability.py`: PASS (0 errors, 7 warnings, as before).
- AC-TREND-3: 50,000 events, each request twice: slowest 0.91 s (trending 0.45/0.61, gap 0.41/0.70, recommendations
  0.44/0.91); identical answers.
- Not run here: the frontend checks and Playwright (no `node_modules` in this worktree; no frontend source changed
  besides the generated types); the legacy runner exits 2 in this sandbox before running (its skip list names ids
  the sandbox's interpreter cannot import), with no legacy file touched.

## P12-F (screens: REQ-TREND-02 frontend, REQ-PERS-01 frontend, REQ-PERS-03 picker)

- Branch `feat/REQ-TREND-02-fe` from P12-B `4a590f1` (in review); agent impl-frontend. Reviews: reviewer, ux-reviewer.
  No backend change; the types are the generated `schema.d.ts` of P12-B.

### Files

| Area | Files (all under `frontend/`) |
|---|---|
| Discover | `app/(app)/dev/discover/{page,DiscoverList,DiscoverControls,ProblemRow,ProjectRow,Chips}.tsx`, `discover.ts` (pure), `data.ts` (server calls) |
| Home | `app/(app)/dev/discover/{RecommendedForYou.tsx,recommendations.ts}`; `app/(app)/dev/page.tsx` (one call, one section) |
| Liked niches and profiling | `app/(app)/dev/discover/niches/{page,NichePicker,ProfilingToggle}.tsx`, `calls.ts`, `picker.ts` (pure) |
| Editor | `app/(app)/dev/ideas/new/page.tsx` (`?problem=`), `editor/EditorScreen.tsx`, `data.ts` (`linkableProblem`), `versions.ts` (`stateWithProblem`) |
| Shared | `components/DevNav.tsx` (+ Discover), `components/discover-icons.tsx`, `lib/i18n/client-strings.ts` (+ `likedNiches`), `locales/{en,sw}.json` (`nav.discover`, `discover.*`, `recommendations.*`, `likedNiches.*`, `_meta.reviewP12f`) |
| Tests | `app/(app)/dev/discover/{discover.test.ts,discover-screens.test.tsx}`, `test/discover.ts` (fixtures), `components/DevNav.test.tsx`, `e2e/discover.spec.ts`, `e2e/support/discover-scene.ts` |

### What it does

- `/dev/discover`: one list at a time in the address (`?view=problems|projects|gap`, `niche`, `county`), a plain GET
  filter form, server-rendered with no script of its own. Problem cards: the badge only when trending, title linking
  to `/problems/{id}`, niche, county or country, proposal count, statement, at most two Why chips (one beside a badge,
  which already states the counts), the rest with the three newest sources and the projects solving it under "More
  about this problem", and "Start a proposal from this problem". Projects always show the problem they solve beside
  them (AC-TREND-2); no organisation count or name. Cold start titles the list "New this week". At most 20 per list.
  Empty lists are one sentence and one action (clear the filters when they narrowed it).
- Home "Recommended for you": the first 3 in ranker order; each card shows the problem (a link to its card), the
  pursuit chip ("Pursue · Good fit", from the `decision` and fit enums mapped to our own keys, never the API's
  `pursuit.label`) and one Why chip; the reasons, Why and Why not are under a disclosure. A one-line note says
  whether the ranking uses activity (`personalised`) and links `/dev/discover/niches#profiling`. No liked niches: the
  picker prompt. No items: empty state. A failed ranker call leaves Home standing ("cannot be shown right now").
  `features` is never read.
- `/dev/discover/niches`: 3 to 5 checkboxes (children under their parent), counted before sending; PUT sends the
  whole list, so it changes but is never cleared (the page says so); 422 `liked_niches_count` and `unknown_niche`
  are fixed sentences. Below it, the profiling consent: the API's wording verbatim, recorded on its version with
  `PUT /api/me/consents` (409 `consent_text_changed` asks for a reload). There was no consent setting screen, so
  this is "the consent setting" Home links to.
- "Start a proposal from this problem" opens `/dev/ideas/new?problem=<id>`: the editor did not accept a problem, so
  `new/page.tsx` now reads it, `EditorScreen` fetches `GET /api/problems/{id}` and starts in "Link a listed problem"
  with that problem and its niche; nothing is saved until the developer types (P13-F edits the same editor next).

### Tests

- vitest: 18 pure (`discover.test.ts`: address parsing, chips ≤ 2, cold start, safe source links, dates, picker
  rules and refusals, Home states, `stateWithProblem`) and 16 screen tests (`discover-screens.test.tsx`: badge only
  when trending, links, disclosure contents, projects beside problems, 20 cap, empty states, pursuit and Why chips,
  personalised note, Not now / Consider / Exploring / Why not, picker count and refusals, profiling toggle and 409).
- Playwright `e2e/discover.spec.ts` (M2 walkthrough step 4), both projects: a new developer sees the picker prompt on
  Home, is refused at 2 niches, saves 3, sees Discover with the demo's trending problem (badge, Why chip, sources,
  project), the Projects view (each project's problem linked, no organisation counts), the Opportunity gap (< 3
  proposals each), a niche filter, Home recommendations (pursuit chip + one Why chip, reasons on demand, the
  personalised note and its link), opens a problem card; "Start a proposal" opens the editor with the problem
  linked; a filtered empty list is one sentence and one action. `checkWidths` runs axe, the one-primary-action and
  no-horizontal-scroll checks at 360 and 375 (mobile project) and 1440 (desktop). It uses the demo seed's trends, as
  the CI e2e job seeds them (`discover-scene.ts` fails with how to seed when they are missing); no owner database
  access is needed.

### Open items

1. **Problem card route.** `/problems/{id}` is REQ-RES-01's (`feat/REQ-RES-01-fe`), not on this base: the link is
   built by `discover.ts` `problemHref` (the same address as that branch's `components/problem/problem.ts`); after
   both merge, import that one and add a heading assertion after "opens a problem card" in `discover.spec.ts` (the
   test now checks the address and the card through `GET /api/problems/{id}`). On this base the missing route's
   prefetch never settles in Chromium, so `npm run budget` times out on `/dev` and `/dev/discover` waiting for
   network idle; measured with a load-based copy of the script instead (below). It resolves once the route exists.
2. **Simulated numbers.** The API has no "simulated" flag, so Discover does not label the demo's numbers; P16's
   README "real vs simulated" table must list Discover's trend counts and badges (demo signals from pseudonyms, card
   open item 5) and the keyword-based fit.
3. **English chips.** Why chips, badges, pursuit reasons and Why-not lines are the API's English text
   (`[[COPY-REVIEW]]` in `bridge/matching`); the Swahili UI would show them in English. The fit and pursuit words are
   mapped to our keys and translated. Translating the chips needs codes from the API (a later P12-B change).
4. **D-47.** `likedNiches.profiling.lead` states today's behaviour (niches and county always, activity only with the
   consent) next to the consent's own wording ("Use my niches and activity …"); if D-47 goes to option (b), change
   the lead and the Home note.
5. **Swahili nav at 360 px.** Five tabs fit in English at 360 px; Swahili labels ("Mawazo yangu", "Ushirikiano")
   are a little longer and Swahili is off until G5: check the tab bar at 360 px when it goes live.
6. **P12-B fix round.** Nothing here reads `features` or `pursuit.label`; after the tighter types land, regenerate
   `schema.d.ts` only (`test/discover.ts` casts the fixture past `features`).

### Checks

- eslint, `tsc` (`npm run typecheck`), vitest, `npm run api:check`, `scripts/copy_lint.py`, traceability: see the
  report. JS per route (production build, gzipped, load-based count): `/dev` and `/dev/discover` (all three views)
  140.1 KB, `/dev/discover/niches` 143.1 KB (budget 150; the AccountMenu from integration adds about 1.2 KB).
- Screenshots (375 and 1440): `p12f-{home,discover,projects,niches}-{375,1440}.jpg` in the P12-F session scratchpad.
