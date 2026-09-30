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
  scores: no z-score (cold start). Trending = z >= 1.0, score >= 1.0, >= 3 distinct actors. New this week =
  published in the last 7 Nairobi days (6 days old is new, 7 is not).
- Actors (fix rounds 1 and 2) are only the people and organisations behind recent activity, all in the 30-day badge
  window: developers with a proposal against the problem, publishers of sources dated in it, the Brief's
  organisation when the Brief was posted in it, and the organisations whose scouts matched a linked proposal in it
  (a second `app_trend_aggregates` call whose `since` is the window's first Nairobi day; the definer still counts
  organisations only from 3, and the "N companies scouting" chip quotes that recent count). A project's actors are
  the organisations that expressed interest in the window. Scores still use the whole 180-day window. Chosen over dropping
  publishers entirely: fresh independent coverage by three publishers is a real crowd for a research card, while a
  year-old or two-month-old source is evidence for the score, not a person acting now. A card with three sources 35
  to 37 days old and one new proposal has one actor and no badge
  (`test_discover.py::test_old_sources_are_evidence_not_actors`).
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
- Opportunity Gap (fix round, review MINOR 1: a z floor, not a platform-wide decile): the problems in the filter's
  scope that have a z-score and a positive score, ranked by z; the top `ceil(10 %)` of that scope; of those, the ones
  whose z reaches the Trending floor (1.0) and that have fewer than 3 published proposals. With a niche filter the
  decile is the niche's; the floor keeps a quiet scope's top tenth, which is no trend, out. A platform-wide decile
  was not chosen: a small niche would never reach it, against spec 6.6's "so small niches can trend".
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
ids are uuid5 of the signal's Nairobi date, proposal, kind and organisation, and its time is that date's 00:05 plus
a few minutes (never after the run): a run on the same day inserts nothing, a later run adds only the dates earlier
runs did not cover, so there is never more than one signal per proposal, kind, organisation and date
(`unit/demo/test_demo_trending.py`, two runs a week apart). Choices made in the app (niches set, consent decided) are
kept.

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
  trend: TrendOut, features: FeaturesOut}`; `FeaturesOut` has exactly the ten named fields `semantic_fit,
  niche_match, region_match, skill_coverage, trend, evidence_confidence, market_pull, crowding, track_record,
  freshness`, each a `FeatureOut {raw, value, weight, applies}`. 404 without a developer
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
3. **The definer's plan on a table without statistics.** Measured on a fresh database: 5k events 6.5 s, 20k events
   116 s, 50k events about 150 s for the first `app_trend_aggregates` call; after `ANALYZE signal_events`, 0.2 s at
   50k. The planner takes a just-loaded table as empty and picks a nested plan. Autovacuum's analyse fixes it in
   normal growth, but a restore, a bulk import or a fresh replica would serve Discover slowly until then. For
   0006: look at the plan (an index serving the definer's grouping, e.g. on `(kind, item_id, ts)`, or a plan that
   does not depend on the estimate). **Runbook note** (for the deploy/restore runbook when it is written): run
   `ANALYZE signal_events` (or `ANALYZE` of the database) right after a restore or bulk load.
4. From the 0005 re-check, still open: snap `p_since`/`p_now` to Nairobi day boundaries inside the definer (the
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

1. **Definer performance without statistics**: moved to "Needs a revision" item 3 (with the runbook note). The perf
   test runs ANALYZE the way autovacuum would.
2. **Consent wording vs. behaviour**: recorded as **D-47** on integration (default (a): niches and county are
   declared preferences used without the consent; the text changes to activity only with the D-39 review).
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

## Fix round 1 (reviewer CHANGES_REQUIRED on 4a590f1)

| Finding | Change | Commit | Test |
|---|---|---|---|
| MAJOR: old publishers counted toward the 3-actor floor | actors only behind recent activity (see "Trends" above; publishers kept, but only for sources in the 30-day window; developers likewise) | `cf0c05f` | `test_discover.py::test_old_sources_are_evidence_not_actors` (fails on the old rule) |
| MINOR 1: gap decile | a z floor at the Trending floor; decile stays the scope's (see "Discover") | `19e70ce` | `test_opportunity_gap.py` (exactly 3 proposals is out; a quiet niche has no gap) |
| MINOR 2: surviving mutants | tests for: no history read without consent; `< 3` at exactly 3; once per developer and day at the board; the scouts' daily maximum across a problem's proposals; a held problem's link; the county filter on projects; the 7-day New boundary | `19e70ce`, `8440349` | review mutants R1-R7 below, all killed |
| MINOR 3: config fail closed | kinds must equal the known set (a missing kind is refused, never a silent zero); `baseline_step_days <= baseline_days`; `type(version) is int` | `7e24534` | `test_ranking_config.py` (4 new refusals) |
| MINOR 4: chip source | f1's chip is "Close to your past proposals" when a shared keyword comes from one, else "Close to your profile" `[[COPY-REVIEW]]` | `9e453fc` | `test_ranker.py::test_the_fit_chip_names_where_the_shared_words_come_from` |
| MINOR 5: demo accumulation | signals keyed and timed by their Nairobi date | `29aa2a5` | `unit/demo/test_demo_trending.py` (two runs a week apart) |
| MINOR 6: cold definer plan | "Needs a revision" item 3, with the restore runbook note | this card | |
| MINOR 7: per-day inference | accepted residual, `THREAT_MODEL.md` §2 (new row after the P10 signal row); scores not rounded | `THREAT_MODEL` commit | |
| MINOR 8: types | `Recommendation.features: FeaturesOut` (ten named fields), `PursuitOut.label: "Pursue" \| "Consider" \| "Not now"`; regenerated with `make api-types` (7.13.0) | `6ef7c5c` | recommendation tests; `openapi --check` |
| MINOR 9: merge conflict | the demo seed's trending test moved before the research section; `git merge-tree` against integration `7812693` reports no conflict | `d0d66d4` | |

Review mutants (scratch script, not committed): R1 once per developer and day at the board, R2 the scouts' maximum
across linked proposals, R3 a held problem's link, R4 the county filter on projects, R5 the 7-day boundary, R6 no
history read without consent, R7 old publishers as actors: 7 killed, 0 survived; plus the gap's `<= 3` and no-floor
mutants: killed.

## Fix round 2 (reviewer and P12-F ux-reviewer, on 2c233a0)

| Finding | Change | Commit | Test |
|---|---|---|---|
| MAJOR 1: scouting organisations counted over 180 days; a Brief's organisation at any age | recent aggregates from a second definer call from the badge window's first Nairobi day (scouts, and project interest); the Brief's organisation only when posted in the window | `e1f7810` | `test_discover.py::test_last_seasons_scouts_are_not_actors` (scouts 150-160 days ago + 1 fresh proposal), `::test_an_old_briefs_organisation_is_not_an_actor` (Brief 170 days ago + 2 fresh proposals); each asserts z >= 1 and score >= 1 but no badge, and fails on the old rule |
| MAJOR 2 (ux): Home said "Trending" from z alone | "Trending in its niche" only when `card.trend.trending` (Discover's rule), else "Rising in its niche" `[[COPY-REVIEW]]`, in chips and pursuit reasons; a pursuit reason is never repeated as a Why chip (the next chip takes its place) | `c87bad6` | `test_ranker.py::test_trending_wording_only_where_discover_says_trending` (z 2.714, not trending) |
| MINOR: owner recency | test only (the gate was right, R2 survived) | `e1f7810` | `test_discover.py::test_old_proposal_owners_are_not_actors` |
| MINOR: proposal keywords | assert the proposal's words are in `proposal_keywords` and a headline-only word is not | `c85a1d1` | `test_without_the_consent_no_history_is_read` |
| MINOR: crowded gap problem | assert its z >= 1.0 and exactly 3 proposals (through the board as the reader sees it) | `c85a1d1` | `test_opportunity_gap.py` |
| MINOR (ux): project badge and chip | badge `Trending in <niche>: verified organisations asking`; chip `Verified organisation interest` (one or several, never a count) `[[COPY-REVIEW]]` | `6cffb58` | `test_discover.py` |

Mutants: the three old actor rules (scouts over the window, a Brief at any age, owners outside the badge window) and
the two ranker ones (Trending from z alone, a reason repeated as a chip) each fail their tests. No API schema
changed in round 2 (`openapi --check` clean without regeneration); only the badge, chip and reason texts did.

## Checks after fix round 2

- ruff, ruff format --check (536 files), mypy strict (538 files): clean; `openapi --check`: clean (no schema change).
- Backend suite: 3935 passed (17 min).

## Checks (after fix round 1)

- `ruff check .`, `ruff format --check .` (536 files), `mypy` (strict, 538 files): clean.
- `python -m bridge.openapi --check`: clean; `openapi.json` and `schema.d.ts` regenerated with `make api-types`
  (openapi-typescript 7.13.0). Against the base branch no existing schema is removed or changed; added:
  `DiscoverProblem, DiscoverSource, FeatureOut, FeaturesOut, LikedNichesIn, LikedNichesOut, OpportunityGapOut,
  ProjectTrendOut, PursuitOut, Recommendation, RecommendationsOut, TrendOut, TrendingOut, TrendingProblem,
  TrendingProject`.
- Backend suite: 3931 passed (13 min 43 s).
- `git merge-tree` against integration `7812693`: no conflict.
- `scripts/copy_lint.py`: PASS. `docs/platform/checks/check_traceability.py`: PASS (0 errors, 7 warnings, as before).
- AC-TREND-3: 50,000 events, each request twice: slowest 0.91 s (trending 0.45/0.61, gap 0.41/0.70, recommendations
  0.44/0.91); identical answers.
- Not run here: the frontend checks and Playwright (no `node_modules` in this worktree; no frontend source changed
  besides the generated types); the legacy runner exits 2 in this sandbox before running (its skip list names ids
  the sandbox's interpreter cannot import), with no legacy file touched.

## Re-review MINORs (P12-B fix round 2, reviewer PASS on 710e3e2; carried)
1. `matching/trend_facts.py:275`: no test pins that a project's actors come from the recent window (mutant Q3, whole-window
   `interest` for `recent_interest`, survived). Add the reviewer's G5: old project interest only → not trending, no
   interest chip.
2. Sock E1 organisations can inflate `scout_match` (three self-signup E1 organisations with scouts): recorded as a
   THREAT_MODEL residual and D-50.
