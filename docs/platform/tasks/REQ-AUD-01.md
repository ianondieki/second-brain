# REQ-AUD-01

- Task: T1.4 (`docs/platform/PLAN.md` Phase 1)
- Agent: db-migrations (trigger, grants); orchestrator (verifier, append helper)
- Files owned: `bridge/audit/`, `backend/alembic/versions/`, `backend/tests/integration/test_audit_chain.py`
- Depends on: T1.3.

## Scope

Append-only hash-chained `audit_events` (seq, prev_hash and event_hash set by a SECURITY DEFINER trigger under `pg_advisory_xact_lock`; UNIQUE(chain_id, prev_hash)); mutable `event_details`; UPDATE/DELETE/TRUNCATE blocked by triggers; app role INSERT/SELECT only; Python chain verifier. The hourly RFC 3161 anchor and the nightly Merkle root move to T2.4 with the TSA client.

## Acceptance criteria and tests

AC-IP-2, audit half asserted early (full AC at Phase 2): UPDATE/DELETE rejected; the verifier detects an edited row (Hypothesis over random event sequences).

## Notes

Stays IN-PROGRESS after Phase 1: its ACs (AC-IP-2, AC-IP-7) close in Phases 2 and 8.
