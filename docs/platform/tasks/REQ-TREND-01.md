# REQ-TREND-01 (with REQ-TREND-02 backend and REQ-PERS-01, prototype part)

- Task: P12-B Trending and the ranker, backend (`docs/platform/PLAN.md` §8, prototype track M2;
  `docs/platform/prototype-m2-plan.md` §1 P12 row, §3 P12 bullet, §6). The screens (`/dev/discover`, Home
  "Recommended for you", the liked-niches picker, Discover in DevNav) are P12-F.
- Agent: impl-backend. Reviews: reviewer. No security-reviewer (plan §5: P12-B writes no Tier-2 view signal).
- Branch `feat/REQ-TREND-01-trending` from integration `84e0af0` (0005, P10, P11, P13, P14 merged).
- Depends on: revision 0005 (`app_trend_aggregates`, D-46), `signal_events` and `developer_niches` (0001),
  `profiling` consent (0001, `consents.yaml`), P10 (`scout_match`, `org_interest` signals), P11 (approved research
  cards), P9 (demo seed). No schema change and no new environment variable (see "Needs a revision" below).

## Plan

1. Signals: `proposal_published` / `proposal_version_published` are already written by the publish path and by the
   moderator's approval of a held proposal (P2, `proposals/service.py` `signal`; tests in
   `integration/proposals/test_publish.py`); nothing to add. P10 writes `scout_match` and `org_interest`.
2. `config/ranking/weights_v1.yaml` and its fail-closed loader `matching/ranking_config.py`.
3. `matching/trending.py`: decayed scores, per-niche z-scores against a 90-day baseline, "New this week", the
   anti-gaming rules that need no new data; `matching/trend_facts.py` reads the facts under RLS and the aggregates
   through `app_trend_aggregates` only.
4. `matching/discover.py`: `GET /api/discover/trending`, `GET /api/discover/opportunity-gap` (niche, county).
5. `matching/ranker.py`: `GET /api/me/recommendations`, in code only (no model: the plan names none for P12).
6. `profiles/niches.py`: `GET|PUT /api/me/niches` (liked niches, RLS).
7. `profiling` consent: without it only liked niches, county and public facts rank.
8. Demo seed `seed/demo/trending.py`.
