# REQ-REM-01

- Task: T3.9 (`docs/platform/PLAN.md` Phase 3); prototype track P6 (`PLAN.md` §8)
- Agent: impl-backend
- Files owned: `bridge/reminders/{health,facts,nudge,wording,render,dispatch,__main__}.py`,
  `bridge/reminders/templates/em7_*.j2`, `bridge/jobs/reminders.py`, the `reminder_nudge` task in `backend/ai/models.yaml`,
  `backend/tests/unit/reminders/`, `backend/tests/integration/reminders/`
- Depends on: REQ-REM-00 (T1.8), REQ-NOT-01 (T1.7), REQ-LLM-01 (T2.2 and P7), schema v3 (P1). Parallel with P5
  (`feat/REQ-ENG-02-tracker`): reads the tracker's rows only, never P5's code.

## Scope

Developer daily reminder EM7/N23 (`docs/spec/06` 6.10, 6.11; `REQUIREMENTS.md` §5 N23): `reminders.dispatch` every 15
minutes, sent at most once per user and Nairobi day, from `send_after` 07:30 EAT, on the shared clock
(`app_clock_now()`, so the test clock drives it). Health is computed by code only (`at_risk`: an item due within 2 BD
with no action, a milestone overdue, a stage past its deadline while a party is awaited, the repo-cold rule only with a
linked repo, never on a weekend; `off_track`: anything overdue more than 7 days or a rework loop of 2 or more), against
the signed agreement's milestones. Sections: Needs you, Waiting on the other party, Health with one-line reasons, drafts
not published, one featured next step. The LLM (task `reminder_nudge`) rewords the headline and the next step from
code-computed fact tuples only; a demo fallback, a failed call, a refused call or a reply that adds a fact answers with
fixed fallback text, marked. In-app always; email with the `reminders` consent, the `em7`/email preference not switched
off, a verified address and no suppression. Trending line: off until Phase 5.

## Acceptance criteria and tests

AC-REM-1 and AC-REM-4/b (`unit/reminders/test_health_rules.py`, frozen Africa/Nairobi dates), AC-REM-3
(`integration/reminders/test_health_agreement.py`), AC-MAIL-3 with REQ-NOT-06
(`integration/notifications/test_daily_uniqueness.py`), the dispatcher (`integration/reminders/test_dispatch.py`), the
wording and its fallback (`unit/reminders/test_wording.py`), the email (`unit/reminders/test_nudge.py`), the jobs and
CLI (`unit/reminders/test_jobs_and_cli.py`).

## Prototype P6 (2026-09-29): built

Branch `feat/REQ-REM-01-reminders` (impl-backend). No schema change, no new environment variable, no route.

- **Health** (`bridge/reminders/health.py`, pure): `assess(fact, today, holidays)` gives `on_track`, `at_risk` or
  `off_track` with code tuples as reasons (`ReasonCode`, party, due date, days, milestone), never prose or a percentage.
  Items: the signed agreement's milestones in developer work (due within 2 BD, or overdue), the organisation's review
  of a submitted milestone (due its review window in BD after the `submit_milestone` event), the stage deadline of each
  awaited party; `off_track` past 7 days or at 2+ `request_changes` events; `repo_cold` only with a linked repo, in
  implementation, on a business day (never in Release 1). Side and terminal states are not assessed.
  `whose_turn` mirrors P5's `state_machine.pending`. Thresholds are code constants (`DUE_SOON_BD` 2,
  `OFF_TRACK_AFTER_DAYS` 7, `REWORK_LOOPS_OFF_TRACK` 2, `COLD_AFTER_BD` 3, `QUIET_AFTER_DAYS` 5).
- **Facts** (`bridge/reminders/facts.py`): one query set for both reminders, read as the recipient under RLS: stage,
  deadline and times on `app_clock_now()` as Nairobi dates, milestones of the signed agreement, signatures of the
  stage's document since the stage began, the developer's contact confirmation, the recorded final payment, who
  proposed the latest terms, submission dates and rework loops from the tracker's events, the developer's latest
  action (event, non-automatic endorsement or signature), the developer's drafts (5 newest).
- **Nudge** (`bridge/reminders/nudge.py`, `render.py`, `templates/em7.html.j2`): Needs you (open milestones due within
  14 days, else the stage's action), Waiting on the other party, Health with one-line reasons, Drafts not published,
  one featured next step; quiet (nothing sent, nothing recorded) when nothing needs the developer, all is on track and
  no draft waits. Text and escaped HTML from one model; party text one line, tag-free, defanged; platform links only.
  Subject and in-app summary are code-rendered. Kind `em7`. `[[COPY-REVIEW]]` on all copy.
- **Wording** (`bridge/reminders/wording.py`; task `reminder_nudge` in `ai/models.yaml`: Haiku 4.5, `free_slots`
  `[1, 2, 3]`, Tier 1, no tools, not batchable): the model sees only `Nudge.fact_lines` (counts, codes, dates, milestone
  numbers, the developer's own titles) as one field owned by the developer, and writes `headline` and `next_step`
  (`NudgeWording`, `demo_fallback()` = `DEMO_TEXT` with `injection_suspected=True`). Its lines are used only when
  `check_wording` passes; since review round 1 it is an allowlist (`bridge/reminders/grounding.py`, see below).
  Otherwise the fixed text answers, with the reason (`not_eligible`, `demo_fallback:<reason>`, `llm_error:<code>`,
  `injection_suspected`, `retry`, `rejected:<check>`), logged `reminders.nudge_worded`, marked in the email header
  `X-Bridge-Wording: model|fallback`; model wording is labelled "AI-drafted" in the email (docs/spec/09).
- **Dispatch** (`bridge/reminders/dispatch.py`): `run_developer_nudges` from 07:30 EAT; per recipient in a session bound
  to them: the day's ledger rows first (done: no facts read, no LLM call), then facts, wording, the in-app summary
  (always on) and the email (the `reminders` consent, a verified address, the `em7`/email preference, a plan with
  `daily_email_reminders`; suppressions via `send_email`; one attempt per run, three per message). One recipient's
  failure is logged and skipped. `ReminderRuntime` builds the session factory, the email provider (Mailpit via
  `SmtpEmailProvider` in dev) and the LLM runtime from settings.
- **Jobs** (`bridge/jobs/reminders.py`, imported by the worker): `reminders.dispatch` and `reminders.org_digest`, cron
  `*/15 * * * *`, queue `reminders`, locks `reminders:dispatch` / `reminders:org_digest`, no retry; they ignore the
  job's timestamp and read the shared clock, so the test clock drives them.
- **Dev/test trigger**: `python -m bridge.reminders run [--now] [--only developers|organisations] [--user ID]`, one pass
  of each at the shared clock's time; `--now` skips the start times (never a second send for a period) and is refused
  under `APP_ENV=production`. P5's test-clock router can call `run_developer_nudges`/`run_org_digests` later.

Tests: `unit/reminders/test_health_rules.py` (AC-REM-1, AC-REM-4/b), `unit/reminders/test_nudge.py`,
`unit/reminders/test_wording.py` (a non-demo account never reaches a free slot; invented facts fall back),
`unit/reminders/test_jobs_and_cli.py`, `integration/reminders/test_dispatch.py` (once per day, 07:30 gate, quiet days,
consent/preference/verification/suppression, marked fallback, free-provider data rule, the test clock moving a day,
retries), `integration/reminders/test_health_agreement.py` (AC-REM-3), `integration/reminders/test_facts.py`.

**Open (for the orchestrator).**

1. `send_after_hour` per user needs a column (db-migrations); every developer uses 07:30 EAT meanwhile.
2. Thresholds and start times are code constants until P5's `backend/config/policy.yaml` merges; then a `reminders:`
   section there. `whose_turn` should then call P5's `state_machine.pending`/`whose_turn` instead of the mirror.
3. The facts read P5's command names `submit_milestone` and `request_changes` (payload `milestone_id`): keep them
   stable, or change `facts.py` with them.
4. Each 15-minute run lists every active user and binds each (RLS allows no cross-tenant listing); fine for the
   prototype; later a SECURITY DEFINER list of candidates (db-migrations) or a per-day skip.
5. docs/spec/09 says reminder wording is a nightly batch: the prototype words each nudge when it is sent (free slots
   have no batch API); the Anthropic batch path is a later cost optimisation.
6. P9 (`seed --demo`) must grant the `reminders` consent to the demo accounts for the emails to flow (in-app flows
   without it) and mark them `demo_account` for model wording on free slots.
7. The trending line (REQ-TREND-02, Phase 5) is not built.
8. Merge with P5: both branches edit `IMPORT_PATHS` in `bridge/jobs/app.py` and its assertion in
   `tests/unit/jobs/test_provenance_jobs.py` (keep all three task modules).

## P6 review round 1 (2026-09-29, at 89851b6): CHANGES_REQUIRED, 2 MAJOR, fixed

- **MAJOR 1** (`5c46e78` red, `c606cfd`, `816ac93`): `check_wording` was a denylist and let invented facts through
  (a name opening a sentence, "paid", "twenty", an ordinal, 2026 as an amount, a day and month from different facts,
  "within a week … cancelled"). It is now an allowlist (`bridge/reminders/grounding.py`): the facts and the model's
  line are read with the same rules; quoted titles, dates (a day with its month, the year when written), counts (a
  number with its noun and status) and milestone numbers are whole units that must be the facts'; every other word
  must be a neutral vocabulary word (no state verbs, negations or names) or a word of the facts; capitalised words
  must be in the facts unless a vocabulary word opens a sentence; ordinals, amounts, quantity words, months without
  a day, weekdays and other time words, statuses the facts lack, symbols, links, contact details and every whitespace
  but a space are refused; the next step keeps its title and dates. The nudge's fact lines state counts as units
  ("2 things need the developer.", "1 engagement at risk.", "Today is 5 Oct 2026."). Reason codes: `invented_word`,
  `invented_number`, `invented_date`, `invented_status`, `<field>_symbol`, `<field>_not_one_line`,
  `<field>_link_or_contact`, `<field>_length`, `next_step_changed`. `unit/reminders/test_grounding.py` holds the
  reviewer's probes. THREAT_MODEL row "Reminder wording misstates milestone status" updated.
- **MAJOR 2** (`a23985a` red, `1e0f0d8`): the model was asked
  for every nudge, though only the email uses its words. It is now asked only when the run sends a new email; a
  resumed email carries the fixed text (reason `retry`), so one model call serves one email and no facts reach the
  model for an in-app summary, a closed email channel (no consent, preference off, unverified, plan) or a retry
  (`test_no_llm_call_when_no_email_will_be_sent`, `test_one_llm_call_per_email_not_per_attempt`).
- MINORs done: a plan without `daily_email_reminders` gives `email_skipped == "plan"` (same test); queued emails of an
  earlier period are swept to `failed` ("expired: its day passed") and a queued email a run will not send ends
  `failed` ("withdrawn: …") (`df45efe`); any whitespace but a space refused (grounding commit); Kenyan landlines in the
  shared phone patterns (`proposals.sanitise.PHONES`, used by `render.defang`; `1158d79`).
- **Follow-up (not built):** the docs/spec/09 progress-reporter eval set (50 milestone-state fixtures, 100% factual
  consistency, missing data always disclosed) belongs to REQ-EVAL-01; score it with `check_wording`.
- Next (orchestrator, after P5 merges): merge the integration branch, switch `health.whose_turn` to P5's
  `bridge.engagements.state_machine.pending` (docs/spec/06 6.9: the state machine is the only definition) and move the
  thresholds into `config/policy.yaml`, before P6 merges.
