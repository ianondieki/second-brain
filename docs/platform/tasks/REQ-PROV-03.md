# REQ-PROV-03

- Task: T2.5 (`docs/platform/PLAN.md` Phase 2)
- Agent: impl-backend; security-reviewer (Fable)
- Files owned: `bridge/proposals/render.py`, `bridge/proposals/views.py`
- Depends on: T2.3, T2.4.

## Scope

Per-viewer marks on Tier-2/3 renders (visible tiled overlay with viewer name, org, `view_id` and EAT date; `view_id` in HTML meta and PDF metadata) and the access log (`document_views`). The trace tool is Phase 3 (T3.10, AC-IP-3/a).

## Acceptance criteria and tests

AC-REPO-2 (`integration/proposals/test_render_marks.py`).
