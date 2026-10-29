# REQ-HYG-02

- Task: T1.1 (`docs/platform/PLAN.md` Phase 1)
- Agent: chore
- Files owned: `.env.example`, `legacy/.env.example` (archive copy)
- Depends on: None.

## Scope

Delete stale `EVOLUTION_*` variables from `.env.example` and docs.

## Acceptance criteria and tests

AC-HYG-02: `scripts/check_hygiene.sh`.

## Notes

Done in `83daf0a`.
