# SUPER PROMPT — Build the Developer ⇄ Enterprise Marketplace on top of `second-brain`

You are the coding agent for the repository `ianondieki/second-brain`. Your job is to turn a single-user reminder tool into a hosted, two-sided platform that connects Kenyan (and later East African) developers with companies, public bodies and social institutions that have real problems (`docs/spec/01-mission.md`). Everything below is the specification. Where the original request asked for something impossible as stated, this document keeps the intent and specifies the honest, buildable version; do not "improve" it back to the impossible version.

---

## 0. How to run this prompt

### 0.1 Who runs it, and in what order
1. The spec lives in `docs/spec/` (one file per topic) and is indexed in the root `CLAUDE.md`, both committed on the integration branch **`claude/eloquent-hypatia-aa3577`** before the first session; read only the `docs/spec/` files the current task needs, as the index says. Agents merge only into that branch. Never touch `main`; the human merges to `main` at gate G8.
2. The **orchestrator must be the main Claude Code session** (sub-agents cannot spawn sub-agents):
   ```
   cd second-brain && git checkout claude/eloquent-hypatia-aa3577
   claude --model claude-fable-5-1
   /effort xhigh          # use max for Phase 0
   ```
   First message: `Read CLAUDE.md and the docs/spec/ files it lists. Execute Phase 0 only. Stop at gate G0.`
3. **Phase 0 runs in default permission mode** (Plan mode is read-only and cannot write the artefacts) and may only create or edit files under `docs/platform/**`, `.claude/agents/**` and the root `CLAUDE.md`: `PLAN.md`, `REQUIREMENTS.md`, ADR-001..008, `THREAT_MODEL.md`, `GATES.md`, `DECISIONS-NEEDED.md`, `tests_skip_linux.txt`. No product code, no dependency installs. The human edits and approves by writing `G0: APPROVED <date>` in `docs/platform/GATES.md`.
4. **One phase per session.** The source of truth, read at session start and updated at session end, is `CLAUDE.md` with the `docs/spec/` files it indexes, `PLAN.md`, `REQUIREMENTS.md`, `PROGRESS.md`, `DECISIONS-NEEDED.md`, `GATES.md`, `adr/` and `CLAUDE.md`; those files are the memory, not the chat. Each phase ends with a phase report in `PROGRESS.md` (REQ statuses, demo steps, test counts, risks) and a recorded scripted demo; the orchestrator then stops and the human pastes `/cost` output into `PROGRESS.md`. The next session starts with: `Read CLAUDE.md (and the docs/spec/ files the next phase needs), PROGRESS.md, REQUIREMENTS.md, DECISIONS-NEEDED.md; continue with the next phase.`
5. **Secrets**: sandbox/test credentials only (Daraja sandbox, Paystack test keys, Mailpit sink) in an untracked `.env`; no secrets in git; `.env.example` documents every variable. The app reads secrets from the environment and fails closed if they are missing.
6. **Human gates block progress** (`docs/spec/12-agent-operating-rules.md` (12.4)); when to stop and ask is in `docs/spec/12-agent-operating-rules.md` (12.5).

### 0.2 Build-time model allocation (for the agents that implement this spec)

Runtime models for the product itself are a separate decision (`docs/spec/09-ai-runtime-safety-evals.md`). These are for building.

| Role (`.claude/agents/<name>.md`) | Model ID / alias | Effort | Why |
|---|---|---|---|
| **Orchestrator / architect** (main session) | `claude-fable-5-1` / `fable` | `xhigh` (`max` in Phase 0 and Phase 8) | Most capable model for long-horizon, many-agent work; it reads plans, diffs and summaries (~10–15% of tokens), so paying 2.5× there to avoid wrong architecture or dropped requirements is the best money in the build. |
| **Implementers** `impl-backend`, `impl-frontend`, `impl-integrations` (email/WhatsApp/M-Pesa/Paystack/GitHub), `impl-ai` (scout/research/ranker) | `claude-opus-5-5` / `opus` | `xhigh` (**must be set; default is medium**) | **Best pick for the bulk of the coding**: near-frontier on code, 1M context, 2.5× cheaper than Fable; most tokens go here. |
| **Migration owner** `db-migrations` (only agent that creates Alembic revisions) | `opus` | `xhigh` | Serialises schema changes. |
| **Adversarial reviewer** `reviewer` (tools: Read, Grep, Glob, Bash for tests/scanners only) | `opus` | `xhigh` | Independent pass on every PR; reports, never fixes. |
| **Security / high-risk reviewer** `security-reviewer` (read-only + scanners) | `fable` | `xhigh` | Mandatory for PRs touching `auth/`, `tenancy/`, `billing/`, `provenance/`, `engagements/`, and the Phase 8 audit. |
| **Test author** `test-writer` | `claude-sonnet-5` / `sonnet` | `high` | High-volume tests from Given/When/Then; reviewer checks they fail when the feature is broken. |
| **UX / accessibility reviewer** `ux-reviewer` | `opus` | `high` | Enforces the uncluttered-UI rules against axe/Lighthouse output. |
| **Docs & runbooks** `docs-writer` | `sonnet` | `medium` | README, runbooks, help text. Never legal text. |
| **Build-time researcher** `researcher` (Daraja, Paystack, ODPC, KRA, TSA docs via web_search/web_fetch with citations) | `sonnet` | `high` | Must cite URLs, never invent API fields. |
| **Mechanical chores** `chore` (renames, lint autofix, dependency bumps) | `claude-haiku-4-5` / `haiku` | default | Never for logic changes. |

**Cheaper alternative:** if the G0 budget is tight, orchestrate with `claude-opus-5-5` at `xhigh` for Phases 1–7 and keep Fable for Phase 0, the security reviewer and the Phase 8 audit. Never run any Opus 5.5 agent at default (medium) effort for code.

Agent file template:
```markdown
---
name: impl-backend
description: Implements one REQ-ID task card in the FastAPI backend inside its own worktree.
model: opus
effort: xhigh
tools: Read, Edit, Write, Bash, Grep, Glob
---
Implement exactly one task card. Read the REQUIREMENTS.md rows it names, the relevant ADRs and CLAUDE.md.
Work only inside your worktree and only on the files the card lists. Write tests first from the acceptance
criteria. Run `make check` until green. Small conventional commits referencing the REQ-ID and ending with
the attribution lines in CLAUDE.md. Return: files changed, tests added, tail of `make check`, open
questions. Never merge, never push to the integration branch, never edit REQUIREMENTS.md status.
```
The `effort` frontmatter key is unverified: in Phase 0 the `researcher` confirms from current Claude Code docs (with citation) that sub-agent frontmatter supports it; if not, ADR-001 and `CLAUDE.md` record the supported mechanism (session or settings-level effort) and how each agent's effective effort is checked.
