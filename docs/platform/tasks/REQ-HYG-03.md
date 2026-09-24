# REQ-HYG-03

- Task: T1.1 (`docs/platform/PLAN.md` Phase 1)
- Agent: chore
- Files owned: `.env.example`, `README.md`, `legacy/README.md`
- Depends on: None.

## Scope

Example `GROQ_MODEL=openai/gpt-oss-20b` (code untouched); the README legacy section naming the retired model moves to `legacy/README.md`.

## Acceptance criteria and tests

AC-HYG-03: `scripts/check_hygiene.sh`.

## Notes

Done in `83daf0a`, `6286d7e`.
