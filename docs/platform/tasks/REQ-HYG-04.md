# REQ-HYG-04

- Task: T1.1 (`docs/platform/PLAN.md` Phase 1)
- Agent: chore
- Files owned: `.env.example`
- Depends on: None.

## Scope

`TZ=Africa/Nairobi` in `.env.example`; the old Lagos zone appears only in `legacy/` and the spec.

## Acceptance criteria and tests

AC-HYG-04: `scripts/check_hygiene.sh`.

## Notes

Done in `83daf0a`.
