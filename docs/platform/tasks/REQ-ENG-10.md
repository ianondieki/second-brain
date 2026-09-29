# REQ-ENG-10

- Task: P5 (`DECLINED`, `WITHDRAWN`). Design: `REQ-ENG-01.md` ("P5 — tracker main path").
- Agent: impl-backend.

## Scope built in the prototype

`DECLINED` by the organisation (reason codes; see REQ-ENG-05) and by the developer at stage 0 (`BY_DEVELOPER`);
`WITHDRAWN` by the developer from SUBMITTED to AGREEMENT_SIGNING (refused once the agreement is signed): the tag is
withdrawn and closed, Tier-2 access stops (`app_tier2_granted` denies a WITHDRAWN engagement), and the organisation's
people on the engagement are told in-app. Both are terminal: every later command is 409.

## Tests

`tests/integration/engagements/test_tracker_branches.py`.

## After the prototype

`EXPIRED`, `ON_HOLD`, `DISPUTED` (legal hold, mediator), `TERMINATED`, `INFO_REQUESTED`, `PROCUREMENT_ROUTE`;
`frontend/e2e/tracker-branches.spec.ts`.
