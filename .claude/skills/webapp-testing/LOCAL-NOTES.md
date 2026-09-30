# Local notes (Bridge)

Added by Bridge on 2026-09-30. Not part of the upstream skill; the upstream files in this folder are unchanged
copies of anthropics/skills `skills/webapp-testing` at 8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4. The only local
change is that `scripts/with_server.py` is stored without the executable bit; run it as `python scripts/with_server.py`,
as the skill already says. Provenance: `docs/platform/research/design-skills.md`.

## Precedence

- `CLAUDE.md` (Build workflow step 5: Playwright screenshots at 375px and 1440px) and `docs/spec/07` win over this
  skill wherever they differ.
- The repo's e2e conventions win: specs live in `frontend/e2e/*.spec.ts` (TypeScript `@playwright/test`), configured
  by `frontend/playwright.config.ts` and run against the local stack from `make dev`. Use this skill's Python
  scripts only for ad-hoc inspection and screenshots, never as a replacement for the e2e suite.

## Waiting

- `networkidle` has hung our e2e runs. Do not copy the skill's `page.wait_for_load_state('networkidle')` pattern.
  Prefer explicit waits on what the step needs: `expect(locator).toBeVisible()`, `page.wait_for_selector(...)`,
  `page.wait_for_url(...)` or a specific `page.wait_for_response(...)`.
- Point scripts only at local servers (`localhost`). They must never reach a real LLM, email, WhatsApp or payment
  provider (CLAUDE.md, `make check`).
- Write screenshots and logs to the session scratchpad, not to `/tmp/` or `/mnt/user-data/outputs/` as the examples do.
