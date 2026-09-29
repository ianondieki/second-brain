# REQ-ENG-03

- Task: P8 (tracker screens); P5 built the data the screens read. `docs/platform/PLAN.md` §8.
- Agent: impl-frontend (P8), impl-backend (P5 data).

## Scope built in P5 (data only)

`GET /api/engagements/{id}` gives each screen what 6.9 Rendering needs: `state`, `stage_label`, `stage_group` (the
5-group stepper), `whose_turn`, `awaiting` (what moves the engagement on, per party), `actions` (the caller's buttons
only), `due` (business days left, overdue), the current stage's endorsements (name, role, time, method, for the
dual-endorsement rows), agreements, milestones, signatures and payments; the History tab reads `.../history`. Labels
are `[[COPY-REVIEW]]` (`state_machine.STAGE_LABELS`).

## After the prototype

The stepper UI, chips, EAT formatting, whose-turn banner and visual snapshots (P8, then Phase 7 polish).
