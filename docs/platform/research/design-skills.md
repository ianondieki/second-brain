# Vetted design skills: pinning and provenance (REQ-UX-01)

Date vendored: 2026-09-30 (UTC). Every file listed as kept was read in full before it was committed. The upstream
repositories were shallow-cloned once into the session scratchpad and used offline; nothing in this change downloads,
installs or calls the network at run time.

Newly added skills and commands load only in a **new** Claude Code session. A session that was already open when
this branch was checked out will not see them until it is restarted.

## Precedence (applies to every item below)

1. `CLAUDE.md` and `docs/spec/07-ux-information-architecture.md` always win over a skill or command.
2. `docs/spec/04-principles.md` §4.6 (principle 6, Simple UI: ≤5 primary nav items per side, one primary action per
   screen, mobile-first at 360 px, WCAG 2.2 AA) wins over any "add more", "go all out" or "dream big" advice, in
   particular impeccable's core principles and craft-floor's "when torn between refined and committed, commit".
3. Our `reviewer` agent (every PR) and `security-reviewer` agent (`auth/`, `tenancy/`, `billing/`, `provenance/`,
   `engagements/`) stay the required gates. `ux-reviewer` stays the required frontend gate. `/ecc-code-review` is
   an extra pass only.
4. Advice in a vendored file to add a library, service or vendor (for example SWR, `better-all`, `lru-cache`, SVGO,
   WebPageTest, Sentry, a CDN, a self-hosted font) is a suggestion, not a decision: a new dependency or vendor is a
   CLAUDE.md stop condition and goes to `DECISIONS-NEEDED.md`.
5. **System font stack.** spec 07 item 5 / REQ-UX-05 require "one system font stack". That wins over frontend-design's
   "choose your typefaces deliberately, not the default families" and impeccable craft-floor's "Source and self-host a
   face … the closest installed font is a failure" (craft-floor carries a one-line local note saying so).
6. **Tenancy, event log and send rules win over vercel-react-best-practices.** `server-cache-lru` (a cross-request,
   process-wide cache keyed by user or id) would bypass per-request membership checks and Postgres RLS, so it must
   not cache tenant data; `server-after-nonblocking` lists "audit logging" and "sending notifications" after the
   response, but our append-only, hash-chained event log (spec 04 principle 7) and our send rules (spec 06 emails,
   the notification matrix in `REQUIREMENTS.md`) decide how audit events and notifications are recorded and sent; do
   not move them into fire-and-forget `after()` callbacks. Ours win.
7. **Sub-agents.** impeccable `critique` asks for two isolated sub-agents. Run it in single-context mode (with its
   degraded banner) or hand the review to our `ux-reviewer`; do not spawn agents not listed in `.claude/agents/`
   (critique.md carries a one-line note).
8. **Playwright.** Python Playwright (which webapp-testing's scripts need) is not installed and must not be
   installed: it would be a new dependency and a network download. Screenshots and browser checks use the repo's
   TypeScript `@playwright/test` through `frontend/playwright.config.ts`, following `frontend/e2e`. webapp-testing is
   kept as a reference for approach only.

Order the user set for UI work (P16, also in `CLAUDE.md` Build workflow step 5): frontend-design → impeccable →
web-design-guidelines (skipped, see below; impeccable `audit` plus `ux-reviewer` replace it) → Playwright screenshots
at 375 px and 1440 px (TypeScript Playwright via `frontend/playwright.config.ts`; webapp-testing for approach) → axe
(`@axe-core/playwright`, already in `frontend/package.json`) → `ux-reviewer`; plus vercel-react-best-practices over
frontend changes and a local Lighthouse run.

- **Widths, not a contradiction with rule 2:** the 375 px and 1440 px *screenshots* are the user's explicit P16
  instruction. The *automated page checks* (axe, one primary action, no horizontal scroll) run at 360 px, per spec
  04/07 and the `mobile-360` project in `frontend/playwright.config.ts`.
- **Lighthouse:** accessibility ≥90 and performance ≥90 is the user's P16 target, additional to AC-UX-3 (LCP ≤2.5 s
  and JS ≤150 KB gz, throttled). Profile: Lighthouse's default mobile profile (Slow 4G, Moto G-class). Tool: ad-hoc
  `npx lighthouse`, run locally only; it is not added as a dependency. (That `npx` use is the user's instruction in
  CLAUDE.md, not something a vendored skill asks for.)

## Summary

| Item | Installed at | Upstream | Commit | Commit date (UTC) | Licence (file) | Status |
|---|---|---|---|---|---|---|
| frontend-design | `.claude/skills/frontend-design/` | github.com/anthropics/skills `skills/frontend-design` | `8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4` | 2026-09-29 02:20 | Apache-2.0 (`LICENSE.txt`) | Vendored unchanged |
| webapp-testing | `.claude/skills/webapp-testing/` | github.com/anthropics/skills `skills/webapp-testing` | `8a1541c4a3ffa5a20a5a91de0dcf3f0bab1d1ef4` | 2026-09-29 02:20 | Apache-2.0 (`LICENSE.txt`) | Vendored; content unchanged, notes added |
| impeccable | `.claude/skills/impeccable/` | github.com/pbakaus/impeccable `.claude/skills/impeccable` | `0d6b47ea19b63afe15e3f93a44d5d9fbbc6fd275` | 2026-09-30 00:17 | Apache-2.0 (`LICENSE`, `NOTICE.md` from repo root) | Trimmed and modified |
| vercel-react-best-practices | `.claude/skills/vercel-react-best-practices/` | github.com/vercel-labs/agent-skills `skills/react-best-practices` | `063bee94c3f4df8453406c830b0a7df0f2860278` | 2026-08-28 13:36 | MIT, stated in README and frontmatter only; no licence file upstream (`LICENSE-NOTE.md`) | Vendored; one line neutralised |
| web-design-guidelines | not installed | github.com/vercel-labs/agent-skills `skills/web-design-guidelines` | `063bee94c3f4df8453406c830b0a7df0f2860278` | 2026-08-28 13:36 | MIT (as above) | **Skipped** |
| ecc-code-review | `.claude/commands/ecc-code-review.md` | github.com/affaan-m/ECC `commands/code-review.md` | `c70874fae9eb0e5ad0365beb7e2955899fd1d30f` | 2026-09-30 01:24 | MIT, Copyright (c) 2026 Affaan Mustafa (`.claude/commands/ecc-code-review.LICENSE`) | Trimmed and renamed |

Commit dates are converted to UTC from each commit's committer date (`git log -1 --format=%cI`): anthropics/skills
2026-09-28T19:20:03-07:00, impeccable 2026-09-30T00:17:23+00:00, vercel-labs 2026-08-28T15:36:07+02:00, ECC
2026-09-29T20:24:05-05:00. In local time the anthropics and ECC commits fall on the 28th and 29th; in UTC on the 29th
and 30th.

The two large commits, 11bab90 (impeccable, 3,102 lines) and a871678 (vercel-react-best-practices, 7,999 lines),
exceed the ~300-line commit guideline because each is one vendored copy. Their content is the upstream files
verbatim except for the edits listed in sections 3 and 4.

Name clashes checked against `.claude/agents/*` (chore, db-migrations, docs-writer, impl-ai, impl-backend,
impl-frontend, impl-integrations, orchestrator, researcher, reviewer, security-reviewer, test-writer, ux-reviewer) and
built-in commands: the only clash was ECC's `code-review` against the built-in `/code-review`, renamed to
`ecc-code-review`. The react skill folder was renamed to match its frontmatter name (not a clash).

## 1. frontend-design

- Kept (unchanged): `SKILL.md`, `LICENSE.txt`.
- Dropped: nothing (the upstream folder has only these two files).
- Local modifications: none.
- Review: pure design guidance; no commands, network, secrets, git or hooks. "Confirm with the client" and "the
  brief's own words always win" are compatible with the precedence rules above.

## 2. webapp-testing

- Kept (content unchanged): `SKILL.md`, `LICENSE.txt`, `scripts/with_server.py`, `examples/console_logging.py`,
  `examples/element_discovery.py`, `examples/static_html_automation.py`.
- Added: `LOCAL-NOTES.md` (Bridge-authored): **Python Playwright is not installed and must not be installed** (new
  dependency, network download), so this skill's scripts are not run and the skill is a reference for approach only;
  screenshots use the repo's TypeScript `@playwright/test` via `frontend/playwright.config.ts` and the
  `frontend/e2e/*.spec.ts` patterns against `make dev`; 375/1440 px screenshots (user's P16) versus 360 px automated
  checks (spec 04/07, `mobile-360`); `networkidle` has hung our e2e runs, so prefer explicit waits; localhost only;
  write screenshots to the scratchpad.
- Local modification: `scripts/with_server.py` is stored without the executable bit (mode 100644 instead of
  100755). The skill already invokes it as `python scripts/with_server.py`, so behaviour is unchanged, and the
  "no executable files" check stays clean.
- Review: `with_server.py` starts only the server commands the caller passes (`subprocess.Popen(..., shell=True)`),
  polls `localhost:<port>` with `socket.create_connection`, runs the caller's command and terminates the servers.
  No other network access, no installs, no secrets. The examples drive a local Playwright browser against
  `localhost:5173` or a `file://` URL and write to `/tmp` or `/mnt/user-data/outputs` (LOCAL-NOTES redirects that).
  The SKILL.md advice "DO NOT read the source" was not followed here: the script was read in full, per the user's rule.

## 3. impeccable (trimmed)

Kept: `SKILL.md` (modified) and 17 references: `polish`, `audit`, `critique`, `quieter`, `distill`, `clarify`,
`harden`, `adapt`, `layout`, `typeset`, `colorize`, `craft-floor`, `operate`, `routing`, `shape`, `onboard`,
`optimize`. Plus `LICENSE` (Apache-2.0, "Copyright 2025 Paul Bakaus") and `NOTICE.md` from the repository root,
unchanged. `NOTICE.md` credits ehmo's `platform-design-skills` (MIT) for `ios.md` / `android.md`; those files are
dropped here, but the notice is kept as the user asked (Apache-2.0 §4(d) only requires notices that pertain to
what is distributed, so keeping it is harmless).

Dropped, with reasons:

| Dropped | Reason |
|---|---|
| `scripts/impeccable`, `scripts/impeccable.cmd` | Launcher: runs, and on first run downloads, a self-contained binary (network call, bundled binary) |
| `scripts/live-browser.js`, `live-browser-dom.js`, `live-browser-ignores.js`, `live-browser-session.js`, `modern-screenshot.umd.js` | JS bundles for the live-browser overlay and live server |
| `scripts/data/font-index.json` (1.1 MB), `font-index-failures.json`, `scripts/command-metadata.json`, `scripts/VERSION` | Launcher data; unused without the launcher |
| `reference/hooks.md` | Defines and manages a design-detector hook (hooks are rejected) |
| `reference/doctor.md` | Repairs launcher artifacts and the hook |
| `reference/live.md`, `reference/live-setup.md`, `reference/generate.md` | Live-browser iteration: needs the live server and injected scripts |
| `reference/new-work.md` | Launcher-driven new-surface flow that writes PRODUCT.md / DESIGN.md (user decision) |
| `reference/component-review.md`, `reference/region-map.md`, `reference/visualize.md`, `reference/degraded/*` | Live-browser / launcher support files (user decision) |
| `reference/init.md`, `reference/document.md`, `reference/extract.md` | Write PRODUCT.md / DESIGN.md / design-system files; this project must not create them |
| `reference/overdrive.md`, `reference/bolder.md`, `reference/delight.md`, `reference/animate.md`, `reference/craft.md` | "Add more" commands that conflict with spec 04 §4.6 (user decision); `craft` is a deprecated alias |
| `reference/ios.md`, `reference/android.md`, `reference/*.native.md` | Native platforms; Bridge is a web app |

No kept reference needed the launcher to make sense after its launcher steps were neutralised, so none was dropped
for that reason. `routing.md` and `critique.md` are the most affected: routing's signal-driven menu is now driven by
what the agent reads; critique keeps its two isolated assessments, but Assessment B is now browser/screenshot and
code evidence instead of the detector, and snapshot persistence is gone.

Each of the 10 modified references (routing, shape, craft-floor, polish, audit, critique, layout, typeset, colorize,
adapt) starts with the Apache-2.0 §4(b) line "> Modified by Bridge (2026-09-30) from pbakaus/impeccable@0d6b47e;
changes listed in docs/platform/research/design-skills.md"; `SKILL.md` carries the longer notice below. Edits use the
phrase "(not available in this copy; do this step by reading the code and screenshots)" (abbreviated **NA** here)
where a step still has a manual equivalent, and "skip … (not in this copy)" where it has none.

Fix round (commit 4a95be6, after review) reworded these dangling lines to "skip" or removed them:
- `SKILL.md` Modes: "persist it only in that surface brief" → "this copy writes no surface brief, so state the mode
  in your response".
- `shape.md`: "New-work owns visual-world and concept choices" → they come from the project context in Phase 2;
  Phase 2 "new-work.md is NA" → "skip the new-work.md step (not in this copy)".
- `critique.md`: Purpose "snapshot persistence is NA" → "skip snapshot persistence"; Setup step 2 → "Skip the slug,
  persistence and trend steps"; "before seeing detector output" → "before seeing Assessment B's output"; removed "The
  persisted snapshot must record the applicable maximum …"; Persist the Snapshot → "Skip this step"; Assessment B
  now names TypeScript Playwright via `frontend/playwright.config.ts`, 375/1440 screenshots, 360 px automated checks,
  and that Python Playwright is not installed and must not be; added the one-line single-context / `ux-reviewer`
  note under Assessment Orchestration.
- `audit.md`: "The bundled detector is NA" → "Skip the bundled detector (not in this copy); find these issues by
  reading the code and screenshots".
- `polish.md`: the native simulator/emulator clause → "screenshots at 375px and 1440px; automated checks at 360px.
  Native platforms are out of scope"; snapshot close → "Skip closing a stored critique snapshot".
- `layout.md`: restored the removed "A clean scan cannot prove hierarchy or rhythm." as "A clean code-and-screenshot
  check cannot prove hierarchy or rhythm." and added "(automated checks run at 360px)".
- `typeset.md`: restored "A clean scan is a floor, not proof of good typography." as "A clean code-and-screenshot
  check is a floor, not proof of good typography."
- `craft-floor.md`: added "(Bridge: spec 07 item 5 / REQ-UX-05 require one system font stack; that wins over this
  line.)" after the self-hosted-face line.

The list below is the original edit set (commit 11bab90).

**`SKILL.md`** (Apache-2.0 §4(b) modified-file notice added):
- Frontmatter `description`: removed animate, extract, bolder, delight, live-browser iteration and "technically
  extraordinary" effects; added "(Bridge copy: launcher, scripts, hooks and live-browser features removed.)".
  `argument-hint`: removed dropped commands. `name`, `version`, `user-invocable`, `license` unchanged.
- Added at the top of the body: the "Modified by Bridge (2026-09-30): launcher, scripts, hooks and live-browser
  features removed; this copy always runs in the skill's own 'Launcher unavailable' mode" notice, with upstream
  commit and licence pointer; and a precedence paragraph (CLAUDE.md, spec 07 and spec 04 §4.6 win, including over
  "go all out / dream big"; `ux-reviewer` stays the gate; read those three files wherever a reference says
  PRODUCT.md / DESIGN.md / surface brief; never create PRODUCT.md or DESIGN.md; references to dropped files are NA).
- Setup step 1: the `scripts/impeccable context` launcher instruction replaced with the fallback: read `CLAUDE.md`,
  `docs/spec/07`, `docs/spec/04` §4.6 directly; no PRODUCT.md/DESIGN.md; do not create them.
- Setup step 2: the `new-work.md` route replaced with "use `shape` and the project context".
- "Launcher unavailable" paragraph: rewritten to say this copy always runs in that mode (no "send a separate
  message" step, since there is no launcher to fail).
- How to design: two mentions of new-work / DESIGN.md replaced with "the project context".
- Modes: the `new-work.md` link removed; added "Bridge's product surfaces are Operate or Read; spec 07 governs them".
- Commands table: removed rows `craft`, `init`, `document`, `extract`, `bolder`, `animate`, `delight`, `overdrive`,
  `live`, `generate`; removed the `audit.native.md` and `adapt.native.md` links from the audit and adapt rows.
- Routing bullets: removed "(native variant on native platforms)"; the "Otherwise" bullet no longer routes through
  init / new-work / `impeccable context`; the `teach`/`craft` alias bullet replaced with "`shape` owns task discovery
  and returns a brief; it never writes code"; the "After init writes PRODUCT.md" paragraph removed.
- Removed the Pin/Unpin, Hooks and Doctor paragraphs and the "Never repair drift" paragraph that belonged to them.

**`reference/routing.md`**:
- "Setup has already run `impeccable context` … run `scripts/impeccable signals`" → reads the project context, the
  `impeccable signals` helper is NA, use what you read plus the branch's changed files.
- The signal bullets (`setup.hasDesign` → document, `critique.latest`, `git.changedFiles`, `devServer.running` →
  live/generate, `setup.platform`) → four plain bullets (no critique yet → critique; P0/P1 left → polish; changed
  files → scoped audit/polish; otherwise group by intent).
- "Reason over the signals" → "Reason over what you read".
- The `scripts/impeccable detect --json` paragraph → detect is NA; fold what you see into the picks.
- Kept: the link to `https://impeccable.style/docs/` (a link for the user, not a fetch).

**`reference/shape.md`**: the `new-work.md` step → new-work is NA; resolve direction from CLAUDE.md, spec 07 and
spec 04 §4.6 plus the discovery answers.

**`reference/craft-floor.md`**: "When the design hook is active it already enforces the mechanical checks…" → "The
design hook is NA."

**`reference/polish.md`**:
- "recommend redesign or `bolder`" → "recommend redesign" (`bolder` dropped).
- The `scripts/impeccable critique-storage latest` block and its explanation → use a critique from this session;
  stored snapshots are NA.
- "Follow the quality guidance supplied by `impeccable context` and hooks …" → context, hooks and detector are NA;
  run the other QA steps (Playwright screenshots, axe, Lighthouse per CLAUDE.md).
- The final `critique-storage close` block → NA.

**`reference/audit.md`**:
- "Native platforms … route to audit.native.md" → the native variant is not in this copy; Bridge is a web app.
- "Run the bundled detector" → the detector is NA; "Cite verified evidence and detector findings" → "Cite verified
  evidence".
- Both "Suggested command" / "Only recommend commands from" lists: removed animate, bolder, delight, document,
  overdrive.

**`reference/critique.md`**:
- Purpose: "persist a snapshot" removed; persistence NA.
- Hard invariants: Assessment B is browser/screenshot evidence (detector NA); detector absence does not fail the
  run; no detector overlay is ever claimed.
- Setup step 2 (`critique-storage slug`) and step 3 (`.impeccable/critique/ignore.md`) → one step: storage NA, skip
  persistence and trend.
- Assessment B: the `scripts/impeccable detect --json` scan, the `impeccable live-server --background` start and the
  `detect.js` overlay injection → NA; replaced with: open a fresh tab on the local dev URL (`make dev`), screenshots
  at 375 px and 1440 px, console errors, inspect markup/styles for mechanical issues (reworded in the fix round, see
  above: TypeScript Playwright, not webapp-testing's Python).
  Its "Return" line and the "reuse CLI findings / don't rerun detect" paragraph adjusted/removed.
- Report: "Deterministic scan" → "Mechanical evidence"; "Visual overlays" → NA, name the screenshots instead;
  synthesis wording refers to Assessments A and B instead of the detector.
- Deliver the Report: removed the persistence-first warning paragraph. Persist the Snapshot section (temp file,
  `IMPECCABLE_CRITIQUE_META`, `critique-storage write`, `trend`, trend line) → NA, do not write critique files.
- Both command lists: removed animate, bolder, delight, document, overdrive.
- Persona sections: the `impeccable init` "Design Context" source → spec 07 / `docs/spec/01-mission.md` audience.

**`reference/layout.md`** and **`reference/typeset.md`**: the Native bullet (ios.md/android.md) → not in this copy;
the new-work.md route → out of scope / stop and ask (typeset also: no DESIGN.md); the "Mechanical scan: run
`scripts/impeccable detect --scope layout|type`" block → NA, inspect code and 375/1440 screenshots; "final mechanical
scan" / "rerun the scan" → recheck code and screenshots; the "Live-mode signature params" section removed.
typeset also: "detector findings" → "mechanical findings".

**`reference/colorize.md`**: the new-work.md route → stop and ask; "Live-mode signature params" section removed.
(Its "Read DESIGN.md" line is covered by the SKILL.md precedence paragraph.)

**`reference/adapt.md`**: the adapt.native.md route → not in this copy; Bridge is a web app.

**Unchanged**: `clarify.md`, `distill.md`, `harden.md`, `onboard.md`, `operate.md`, `optimize.md`, `quieter.md`.
Notes: `harden`/`optimize` say "test offline", "throttle to 3G", "use a CDN", "WebPageTest", "Sentry" and similar;
these are test ideas and suggestions about the app, not commands the agent runs, and any new vendor falls under
precedence rule 4. `quieter`/`distill` tell the agent to use the AskUserQuestion tool when unclear; that is
compatible with CLAUDE.md. `craft-floor` "Source and self-host a face" conflicts with spec 07 item 5 (system font
stack) and loses; see precedence rule 5.

## 4. vercel-react-best-practices

- Folder renamed from `react-best-practices` to `vercel-react-best-practices` to match the frontmatter
  `name: vercel-react-best-practices`, so the skill loads under its declared name.
- Kept: `SKILL.md`, `AGENTS.md`, `metadata.json` and all 72 files in `rules/` (70 rules plus `_sections.md` and
  `_template.md`), unchanged except below.
- Added: `LICENSE-NOTE.md`. Upstream has **no LICENSE file and no copyright line** at this commit (checked with
  `git ls-files` for any licence/notice/copying file and a grep for "copyright"; the root `package.json` has no
  `license` field). The note quotes the README "## License" section (`MIT`) and the SKILL.md frontmatter
  (`license: MIT`, `author: vercel`) verbatim, with repo, commit and date. No copyright line was invented.
- Dropped: `README.md` of the skill folder. It is contributor documentation for a build system that is not vendored
  (`src/`, `test-cases.json`) and tells the reader to run `pnpm install`, `pnpm build`, `pnpm validate` and
  `pnpm extract-tests`: an install instruction, which the user's rules reject. The skill does not reference it.
- Modified: `rules/rendering-svg-precision.md` and the same section 6.4 of `AGENTS.md`: the
  ```` ```bash npx svgo --precision=1 --multipass icon.svg ``` ```` block (npx downloads and runs a package) was
  replaced with "**Automate with SVGO:** not available in this copy. Bridge local change: …" explaining that SVGO
  would be a new dependency and to reduce precision by hand or with a tool already in `frontend/package.json`.
- Review: all "hooks" matches are React hooks (useEffect, useState and so on). Code samples call `fetch` inside
  example application code; nothing tells the agent to make network calls. Library suggestions (SWR, `better-all`,
  `lru-cache`, `@vercel/analytics`) fall under precedence rule 4. `rendering-hydration-no-flicker` shows
  `dangerouslySetInnerHTML` with a static inline script; our CSP rules (`frontend/security-headers.ts`) win.

## 5. web-design-guidelines: SKIPPED

Its `SKILL.md` has no rules of its own. On every run it tells the agent to "Fetch fresh guidelines before each
review" from `https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md` with WebFetch
and to follow "the fetched content", which "contains all the rules and output format instructions". That is a
network call on every use, the rules live in a repository the user did not list or vet, and the fetched text would
act as unreviewed instructions. Replacement: impeccable `audit` (accessibility, performance, theming, responsive,
implementation integrity) plus our `ux-reviewer` agent against spec 07.

## 6. ecc-code-review (from ECC `commands/code-review.md`)

- Installed as `.claude/commands/ecc-code-review.md` (renamed so it does not shadow the built-in `/code-review`).
  Invoke as `/ecc-code-review` (uncommitted changes) or `/ecc-code-review --branch` (committed branch changes).
- Licence: ECC's MIT `LICENSE` copied unchanged to `.claude/commands/ecc-code-review.LICENSE` (next to the command,
  not in a `third_party/` note), and the copyright line is repeated in the command's modified-by note.
- Kept: Local Review Mode (Phase 1 GATHER `git diff --name-only HEAD`, Phase 2 REVIEW checklist, Phase 3 REPORT)
  verbatim except "review of uncommitted changes" → "review of local changes".
- Removed: the "PR review mode adapted from PRPs-agentic-eng by Wirasm" header line (moved into the modified-by note
  as attribution), Mode Selection, the whole PR Review Mode (Phases 1–8: `gh pr view/diff`, `gh api` content
  fetches, `npm`/`npx`/`cargo`/`go`/`pytest` validation runs, writing `.claude/reviews/pr-<N>-review.md`,
  `gh pr review` and `gh api …/comments` posts to GitHub), and the Edge Cases lines "No `gh` CLI" and "Diverged
  branches: suggest `git fetch origin && git rebase origin/<base>`". The "Large PRs" edge case is kept, reworded to
  "Large change sets".
- Added: new frontmatter `description` and `argument-hint`; the modified-by note (MIT permits modification); the
  line that this review is an extra pass only and that `reviewer` and `security-reviewer` stay the required gates;
  an optional read-only `git diff --name-only origin/claude/eloquent-hypatia-aa3577...HEAD` for committed branch
  changes (the remote ref, as last fetched; the command does not fetch). CLAUDE.md Build workflow step 7 names
  `/ecc-code-review` as the ECC pass, with the built-in `/code-review` as the fallback.
- Dependencies: Local Review Mode uses only `git diff` and file reads. It references no other ECC agent, skill,
  hook, rule or script. The upstream description mentioned ECC's `/review-pr` and `/orch-review`; that description
  was replaced, so no dangling reference remains.

## Checks run before committing

- **Risk grep** `grep -rnE "npx|npm (i|install)|curl|wget|WebFetch|gh |git (push|commit|rebase|reset|checkout|config)|hooks|settings.json|\.env|secret|ignore .*CLAUDE"`
  over `.claude/skills` and `.claude/commands` (rerun after the fix round): 59 matching lines (this document adds 27
  more, all of them descriptions of removals, precedence notes or the grep itself).
  - 44 are false positives where `gh ` is the end of a word ("through", "high", "enough", "Tabs through" and so on).
  - The other 15 are listed below.
  - React hooks (vercel-react-best-practices `SKILL.md`, `AGENTS.md`, 6 rule files): "hooks" as in React hooks
    (useEffect, useState); not Claude Code hooks.
  - Bridge-authored notes that record removals: impeccable `SKILL.md` (2, "hooks … removed", "Launcher
    unavailable"), `reference/polish.md` ("hooks and detector scan are (not available …)"), react
    `rules/rendering-svg-precision.md` and `AGENTS.md` ("the upstream `npx svgo` command was removed"),
    `LICENSE-NOTE.md` ("run `pnpm install`" matches `npm install`; "`npx svgo`"), `ecc-code-review.md` ("suggested
    `git rebase`" in the modified-by note).
  - `CLAUDE.md` step 5 now names ad-hoc `npx lighthouse`, local only, as the user's own instruction (not a vendored
    file).
  - No remaining hit instructs the agent to call the network, install a package, touch secrets or `.env`, change
    git state, define hooks or ignore CLAUDE.md.
- **Executables**: `find .claude/skills .claude/commands docs/platform/research/design-skills.md -type f -perm -u+x`
  returns nothing. `file` reports only text: Markdown (some labelled "JavaScript source" or "Python script" by
  libmagic because of code blocks), one JSON file, four Python scripts (`with_server.py` and three examples; the
  word "executable" in libmagic's label means "script text", the mode is 100644), and licence text. No binaries.
- **Size** (after the fix round): 108 files, about 457 KB in total (frontend-design 19,564 bytes; impeccable about
  152 KB; vercel-react-best-practices 228,688 bytes; webapp-testing about 24.3 KB; `.claude/commands` about 3.9 KB;
  this document about 29 KB), plus two edited lines in `CLAUDE.md` (steps 5 and 7).

## Merge-time edits (2026-09-30, orchestrator, after reviewer PASS round 2)

- CLAUDE.md step 7 keeps the ECC plugin (`/ecc:code-review`, `ecc:code-reviewer`) as the first choice when installed,
  then the vendored `/ecc-code-review`, then the built-in `/code-review`; the ECC pass is extra, never a gate.
- `impeccable/reference/critique.md`: the Hard Invariant on isolated sub-agents now points to the Bridge note (single
  context or `ux-reviewer`), which wins.
- `webapp-testing/LOCAL-NOTES.md`: `with_server.py` is reference only and not run here.
- The six vendoring commits carry the REQ-UX-01 tag; this is tooling for P16, not the two-portal requirement itself.
