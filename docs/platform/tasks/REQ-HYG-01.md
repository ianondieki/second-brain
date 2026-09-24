# REQ-HYG-01

- Task: T1.1 (`docs/platform/PLAN.md` Phase 1)
- Agent: chore then docs-writer (done by the orchestrator in Phase 1)
- Files owned: `README.md`, `legacy/README.md`
- Depends on: None.

## Scope

Remove the Telegram/WhatsApp channel flip-flop from README and kept docs; legacy text moves to `legacy/README.md`.

## Acceptance criteria and tests

AC-HYG-01: `scripts/check_hygiene.sh` (pr.yml `hygiene` job).

## Notes

Done in `6286d7e`.
