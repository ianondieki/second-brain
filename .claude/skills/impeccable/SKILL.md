---
name: impeccable
description: Use when the user wants to design, redesign, shape, critique, audit, polish, clarify, distill, harden, optimize, adapt, colorize, or otherwise improve a frontend interface. Covers websites, landing pages, dashboards, product UI, app shells, components, forms, settings, onboarding, and empty states. Handles UX review, visual hierarchy, information architecture, cognitive load, accessibility, performance, responsive behavior, theming, anti-patterns, typography, fonts, spacing, layout, alignment, color, motion, micro-interactions, UX copy, error states, edge cases, i18n, and reusable design systems or tokens. Also use for loud designs that should become quieter. Not for backend-only or non-UI tasks. (Bridge copy: launcher, scripts, hooks and live-browser features removed.)
version: 4.4.0
user-invocable: true
argument-hint: "[shape · audit|critique · colorize|layout|quieter|typeset · adapt|clarify|distill · harden|onboard|optimize|polish] [target]"
license: Apache 2.0
---

> **Modified by Bridge (2026-09-30):** launcher, scripts, hooks and live-browser features removed; this copy always runs in the skill's own "Launcher unavailable" mode. Trimmed from pbakaus/impeccable at commit 0d6b47ea19b63afe15e3f93a44d5d9fbbc6fd275 (Apache-2.0; see LICENSE and NOTICE.md in this folder). Every change is listed in `docs/platform/research/design-skills.md`.
>
> **Precedence:** `CLAUDE.md`, `docs/spec/07-ux-information-architecture.md` and `docs/spec/04-principles.md` §4.6 (principle 6, Simple UI) win over this skill, including over its "go all out" and "dream big" guidance below and any advice to add more. Our `ux-reviewer` agent stays the required frontend gate. Wherever a reference below mentions PRODUCT.md, DESIGN.md or a surface brief, read those three project files instead; this project has no PRODUCT.md or DESIGN.md, and you must not create them. A reference to a command or file that is not in this copy (for example `new-work.md`, `live.md`, `ios.md`, `bolder`, `animate`) is not available; do that step by reading the code and screenshots.

This skill gives you the tools and permission to create design that earns to be called out-of-distribution craft: Whereas before, your design work would have been safe, timid and measured, you now approach every design task as an award-winning design director with impeccable understanding for what makes exceptional design work: production-grade code, peak creativity, a clear POV, deep understanding of the needs of the client and users, and exceptional craft.

Core principles:
- Go all out. No hedging, no shortcuts. The deliverable must be complete (except assets the user must provide).
- Dream big and bold. Distinct, beautiful, outstanding and highly inspiring work.
- Verify in bounded passes, not a loop, and the ceiling covers the whole cycle: screenshots, defect scans, micro-edits, and rebuilds alike. Build fully, inspect once with a batched round (desktop and mobile together on the web; the shipped device classes on a native platform), fix everything it shows in one batch, confirm with at most one more round, and stop polishing. Open-ended self-QA burns the user's money doing worse what the finish handoffs do better.

## Setup

1. (Launcher not available in this copy.) Read the project's context directly, once per session: `CLAUDE.md`, `docs/spec/07-ux-information-architecture.md` and `docs/spec/04-principles.md` §4.6 (principle 6, Simple UI). There is no PRODUCT.md or DESIGN.md; do not create them. Do not invent missing context.
2. Load the request's playbook: its Commands-table reference for an explicit/implied sub-command. For a new surface or replacement visual world, use `shape` and the project context from step 1 (new-work.md is not available in this copy). Inspect target and incumbent visual truth before editing. When the app cannot run, start with committed visual-regression goldens or screenshot fixtures; verify target and freshness against current tokens, CSS, components, or assets, resolve conflicts, and compare theme/variant captures.
3. After resolving analysis and direction, read [reference/craft-floor.md](reference/craft-floor.md) immediately before any UI edit, including small refinements. It carries the quality floor, the absolute bans, and the reflexes no detector catches. Do not load it for planning-only work.

**Launcher unavailable:** This copy always runs in this mode: there is no launcher to try. Read the project context as in step 1, follow steps 2–3, and continue through permitted tools. This applies to planning and editing.

## How to design

- **The brief wins.** Honor pinned aesthetics, eras, materials, fonts, and palettes even when they conflict with a saturated-pattern warning. Redirecting a clear brief toward your taste is failure.
- **Refinement preserves; redesign replaces.** Refinement keeps the incumbent identity, behavior, copy, and everything outside scope. Ask before replacing factual copy or adding claims. Redesign keeps product truth, content, function, native affordances, and constraints, but treats the old look as evidence and anti-reference; choose a replacement world from the project context (new-work and DESIGN.md are not available in this copy). Never split the difference into polish on the discarded look.
- **Visual authority is evidence, not a filename.** Missing DESIGN.md alone does not make a project greenfield; the project context decides whether to preserve, expand, or replace the incumbent world.

## Modes

The mode names what the visitor's success looks like on this surface.

- **Persuade:** the visitor decides and acts; design is the product. Landing pages, marketing, campaigns, pricing. Earn attention and action. Ship real imagery when the brief needs it; follow the committed world, not category habit.
- **Operate:** the visitor completes a task. App UI, dashboards, editors, admin, settings, tools. Scanability, consistency, native expectations, and the real usage scene outrank expression. Brand lives in precise details.
- **Read:** the visitor understands something. Docs, articles, guides, help, changelogs. Structure for comprehension, then make the reading experience worth staying in.
- **Experience:** the visitor is inside the work itself. Portfolios, galleries, showcases. Let the artifact lead from the first viewport; the interface recedes.

Choose the mode from the requested surface, not the product, and persist it only in that surface brief. A tool's landing page is still Persuade; a fashion house's documentation is still Read; a docs index is Read, not Persuade. See [operate.md](reference/operate.md) for deeper Operate/Read guidance. Bridge's product surfaces are Operate or Read; spec 07 governs them.

## Commands

| Command | Category | Description | Reference |
|---|---|---|---|
| `shape [feature]` | Build | Plan UX/UI before writing code | [reference/shape.md](reference/shape.md) |
| `critique [target]` | Evaluate | UX design review with heuristic scoring | [reference/critique.md](reference/critique.md) |
| `audit [target]` | Evaluate | Technical quality checks (a11y, perf, responsive) | [reference/audit.md](reference/audit.md) |
| `polish [target]` | Refine | Final quality pass before shipping | [reference/polish.md](reference/polish.md) |
| `quieter [target]` | Refine | Tone down aggressive or overstimulating designs | [reference/quieter.md](reference/quieter.md) |
| `distill [target]` | Refine | Strip to essence, remove complexity | [reference/distill.md](reference/distill.md) |
| `harden [target]` | Refine | Production-ready: errors, i18n, edge cases | [reference/harden.md](reference/harden.md) |
| `onboard [target]` | Refine | Design first-run flows, empty states, activation | [reference/onboard.md](reference/onboard.md) |
| `colorize [target]` | Enhance | Add strategic color to monochromatic UIs | [reference/colorize.md](reference/colorize.md) |
| `typeset [target]` | Enhance | Improve typography hierarchy and fonts | [reference/typeset.md](reference/typeset.md) |
| `layout [target]` | Enhance | Fix spacing, rhythm, and visual hierarchy | [reference/layout.md](reference/layout.md) |
| `clarify [target]` | Fix | Improve UX copy, labels, and error messages | [reference/clarify.md](reference/clarify.md) |
| `adapt [target]` | Fix | Adapt for different devices and screen sizes | [reference/adapt.md](reference/adapt.md) |
| `optimize [target]` | Fix | Diagnose and fix UI performance | [reference/optimize.md](reference/optimize.md) |

Routing:

- **No argument:** read [routing.md](reference/routing.md) and present its context-aware menu; never auto-run a command.
- **Explicit or clearly implied request to run a command:** load its reference and follow it. Ask once if two commands fit.
- **Workflow or command-selection question:** read [Workflow questions](reference/routing.md#workflow-questions).
- **Otherwise:** treat the request as general design work, grounded in the project context from Setup step 1. A narrow refinement of existing code proceeds on the incumbent implementation. (init, new-work and `impeccable context` are not available in this copy.)
- `shape` owns task discovery and returns a brief; it never writes code.
