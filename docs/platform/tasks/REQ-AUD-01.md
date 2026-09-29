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

## Phase 2 (T2.4)

Hourly `provenance.anchor_chain_heads` job: an RFC 3161 token over each audit chain head (`chain_anchors`), through the same TSA client as REQ-PROV-01 (local `openssl ts` test CA in tests). Nightly `audit.verify_chain` job and a signed Merkle root over the day's chain heads (`transparency_roots`), readable at `/api/transparency` (the public `/transparency` page follows with the admin console in Phase 8). AC-IP-2 closes at the Phase 2 exit (trigger rejection + verifier detection, manifest half in `unit/provenance/test_tamper.py`); REQ-AUD-01 stays IN-PROGRESS until AC-IP-7 (Phase 8).

## Notes (T2.4, Phase 2 implementation)

- `provenance.anchor_chain_heads` (hourly at minute 7 UTC) timestamps only heads that moved: `provenance_worker` may
  insert into `chain_anchors` but not read it, so the heads with no anchor at their `seq` come from the definer
  function `app_unanchored_chain_heads()` (schema v2; before it, a trial insert in a rolled-back savepoint probed each
  head, which `chain_anchors_guard`'s lower time bound now refuses). At most 500 anchors per run.
- `audit.verify_chain` (21:30 UTC = 00:30 Nairobi) verifies every chain as `audit_reader` in one REPEATABLE READ
  snapshot and only then publishes the RFC 6962 Merkle root of that snapshot's heads (leaf = chain id, 0x00, seq as
  8 bytes big-endian, event hash), signed over `bridge-transparency-root-v1:<day>:<root hex>`, for the Nairobi day
  that just ended, with the snapshot's time (`transparency_roots.snapshot_at`, not covered by the signature). A
  broken chain publishes nothing and fails the job. It needs `AUDIT_READER_DATABASE_URL` (an
  `audit_reader` login; the dev compose stack has none, so there the job fails closed with a clear message).
- `GET /api/transparency` lists the signed roots with their snapshot times (public, newest first).
- Review round 1 (T2.4): capped anchor runs take heads oldest first, then by chain id, and stop at the first failed
  timestamp; `audit.verify_chain` retries transient failures (`VERIFY_RETRY`) but never a broken chain; roots are
  signed only by a published, unretired key. Schema follow-ups (head `occurred_at`, `transparency_roots.snapshot_at`)
  are listed on the REQ-PROV-01 card.
- Tests run on their own database (`tests/integration/provenance/test_transparency.py`): the shared one holds chains
  other tests break on purpose.
- Review round 2 (T2.4): each anchor is inserted in its own savepoint, so one the database refuses is logged
  (`provenance.anchor_rejected`) and retried next hour; a run fails only when none landed (`TsaError` when nothing
  was timestamped, `AnchorRejectedError` when every token was refused). The anchor path takes no token more than
  60 s ahead of the worker clock (`ANCHOR_MAX_AHEAD`, the bound of `chain_anchors_guard`). The task holds the
  Procrastinate lock `provenance:anchors`, commits every 25 anchors and requests no timestamp after a 15-minute
  budget. The transparency tests read the database clock (the one the guards read) and close yesterday in Nairobi.
