# Local notes (Bridge)

Added by Bridge on 2026-09-30. Not part of the upstream skill; the upstream files in this folder are unchanged
copies of anthropics/skills `skills/webapp-testing` at 8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4. The only local
change is that `scripts/with_server.py` is stored without the executable bit; run it as `python scripts/with_server.py`,
as the skill already says. Provenance: `docs/platform/research/design-skills.md`.

## Reference for approach only

- **Python Playwright is not installed in this repo and must not be installed**: it would be a new dependency and a
  network download (CLAUDE.md stop condition). This skill's Python scripts and examples are not run here; read them
  only for the approach (reconnaissance, then action; screenshot, then selectors).
- Screenshots and browser checks use the repo's TypeScript `@playwright/test` through `frontend/playwright.config.ts`,
  following the patterns in `frontend/e2e/*.spec.ts`, against the local stack from `make dev`.

## Precedence

- `CLAUDE.md` and `docs/spec/07` win over this skill wherever they differ.
- Widths: screenshots at 375px and 1440px are the user's explicit instruction for UI work (P16). The automated page
  checks (axe, primary action, horizontal scroll) run at 360px, per spec 04/07 and the `mobile-360` project in
  `frontend/playwright.config.ts`.

## Waiting

- `networkidle` has hung our e2e runs. Do not copy the skill's `page.wait_for_load_state('networkidle')` pattern.
  Prefer explicit waits on what the step needs: `expect(locator).toBeVisible()`, `page.wait_for_selector(...)`,
  `page.wait_for_url(...)` or a specific `page.wait_for_response(...)`.
- Point scripts only at local servers (`localhost`). They must never reach a real LLM, email, WhatsApp or payment
  provider (CLAUDE.md, `make check`).
- Write screenshots and logs to the session scratchpad, not to `/tmp/` or `/mnt/user-data/outputs/` as the examples do.
