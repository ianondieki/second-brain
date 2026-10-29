# REQ-ENG-12

- Task: P5 (test-clock router). Agent: impl-backend.
- Files: `bridge/testclock.py`, `bridge/main.py` (`dev_clock_router`), `backend/Dockerfile` (`WITH_DEV_TOOLS`, named `WITH_TEST_CLOCK` until P9),
  `infra/docker-compose.dev.yml` (build arg).

## Scope built in the prototype

`GET /api/test-clock` and `POST /api/test-clock/advance {days, hours}` move the shared clock forward through
`app_set_test_clock` (revision 0003: forward only, at most 366 days, only where the owner enabled the clock). Mounted
only when `APP_ENV` is not production and the module is in the image; the image deletes the module unless built with
`WITH_DEV_TOOLS=true` (the dev stack sets it); staff admin only in staging (404 for everyone else); left out of the
OpenAPI document. Every tracker time and deadline follows `app_clock_now()`.

## Tests

`tests/integration/test_testclock_excluded.py` (production 404, module absent, Dockerfile default, dev/test moves and
deadlines follow, staging staff-only, disabled clock 409).

## After the prototype

Expiry and reminder jobs driven by the clock (P6, the SLA job); the Playwright paths with the clock (AC-TRACK-4).
