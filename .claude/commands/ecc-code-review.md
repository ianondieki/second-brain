---
description: ECC checklist code review of local changes (uncommitted, or this branch against the integration branch). An extra pass only; the reviewer and security-reviewer agents stay the required gates.
argument-hint: [blank for uncommitted changes | --branch for committed changes on this branch]
---

# Code Review

> **Modified by Bridge (2026-09-30).** Derived from ECC (github.com/affaan-m/ECC) `commands/code-review.md` at commit
> `c70874fae9eb0e5ad0365beb7e2955899fd1d30f`, MIT licence, Copyright (c) 2026 Affaan Mustafa; full licence text in
> `.claude/commands/ecc-code-review.LICENSE`. Renamed from `code-review` to `ecc-code-review` so it does not shadow the
> built-in `/code-review`. Kept: Local Review Mode. Removed: PR Review Mode (adapted upstream from PRPs-agentic-eng by
> Wirasm), which used `gh`, network calls, posted to GitHub, wrote `.claude/reviews/` and suggested `git rebase`, plus
> the Edge Cases lines about `gh` and rebasing. Added: the `--branch` alternative in Phase 1 (read-only `git diff`).
>
> **This review is an extra pass only.** The `reviewer` agent (every PR) and the `security-reviewer` agent (`auth/`,
> `tenancy/`, `billing/`, `provenance/`, `engagements/`) stay the required gates, and `CLAUDE.md` wins over this
> command wherever they differ.

**Input**: $ARGUMENTS

---

## Local Review Mode

Comprehensive security and quality review of local changes.

### Phase 1 — GATHER

Uncommitted changes (default):

```bash
git diff --name-only HEAD
```

Committed changes on this branch (when `$ARGUMENTS` contains `--branch`), against the remote integration branch
(uses the last fetched `origin/` ref; this command does not fetch):

```bash
git diff --name-only origin/claude/eloquent-hypatia-aa3577...HEAD
```

If no changed files, stop: "Nothing to review."

### Phase 2 — REVIEW

Read each changed file in full. Check for:

**Security Issues (CRITICAL):**
- Hardcoded credentials, API keys, tokens
- SQL injection vulnerabilities
- XSS vulnerabilities
- Missing input validation
- Insecure dependencies
- Path traversal risks

**Code Quality (HIGH):**
- Functions > 50 lines
- Files > 800 lines
- Nesting depth > 4 levels
- Missing error handling
- console.log statements
- TODO/FIXME comments
- Missing JSDoc for public APIs

**Best Practices (MEDIUM):**
- Mutation patterns (use immutable instead)
- Emoji usage in code/comments
- Missing tests for new code
- Accessibility issues (a11y)

### Phase 3 — REPORT

Generate report with:
- Severity: CRITICAL, HIGH, MEDIUM, LOW
- File location and line numbers
- Issue description
- Suggested fix

Block commit if CRITICAL or HIGH issues found.
Never approve code with security vulnerabilities.

---

## Edge Cases

- **Large change sets (>50 files)**: Warn about review scope. Focus on source changes first, then tests, then config/docs.
