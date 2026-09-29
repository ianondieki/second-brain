# REQ-ENG-02

- Task: P1 (schema: `engagement_events` hash chain, projection; see `REQ-ENG-01.md`) and P5 (the History API);
  `docs/platform/PLAN.md` §8.
- Agent: db-migrations (P1), impl-backend (P5). Design and results: `REQ-ENG-01.md` ("P5 — tracker main path").
- Files (P5): `bridge/engagements/history.py`, `schemas.py`, `router.py` (`GET /api/engagements/{id}/history`).

## Scope built in the prototype

The History tab's data: every event of the engagement's hash chain (seq, time, actor and display name, role, command,
states, end reason, deadline, payload, hashes) and every endorsement (stage, round, milestone, party, name, role,
method, time), identical JSON for both parties (AC-TRACK-3's data half), with `chain_verified` from the independent
verifier (`bridge.engagements.chain`). Every endorsement is named by an event's payload (`endorsement_id`), so the
chain carries it. Payloads hold ids, codes, dates, amounts and digests only.

## Tests

`tests/integration/engagements/test_tracker_path.py` (History parity across four people, chain verified, every
endorsement named by an event), `test_tracker_branches.py` (payloads of declines).

## After the prototype

Internal notes (cannot change state), the daily RFC 3161 stamp of chain heads, `test_history_parity.py` in every
locale, the Hypothesis stateful test (AC-TRACK-2).
