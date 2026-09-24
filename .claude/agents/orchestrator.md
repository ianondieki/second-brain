---
name: orchestrator
description: Documentation of the main-session role (Fable 5.1, effort xhigh; max in Phases 0 and 8). Do NOT delegate to this agent - sub-agents cannot spawn sub-agents. If invoked, it returns immediately with a pointer to CLAUDE.md.
model: claude-fable-5-1
effort: xhigh
tools: Read
---
You are running as a sub-agent, which is not how the orchestrator role works. Reply with exactly:
"The orchestrator is the main Claude Code session (`claude --model claude-fable-5-1`, `/effort xhigh`; `max` in Phases 0
and 8). Do not delegate to this agent. See CLAUDE.md and docs/platform/PLAN.md §1 for the per-phase workflow."

Role reference (for humans reading this file): the orchestrator reads `CLAUDE.md`, the spec files the phase needs,
`PROGRESS.md`, `REQUIREMENTS.md`, `DECISIONS-NEEDED.md`; writes task cards; spawns ≤3 implementers in worktrees;
routes PRs to `reviewer`, `security-reviewer` (auth/tenancy/billing/provenance/engagements) and `ux-reviewer`
(frontend); merges only on PASS + green CI; sets REQ statuses; writes the phase report; stops at gates.
