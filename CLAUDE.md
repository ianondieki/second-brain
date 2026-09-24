# CLAUDE.md

## Platform spec index

The build spec for the developer ⇄ enterprise platform is split into topic files under docs/spec/. Read only the files the current task needs.

| File | Read it when |
|---|---|
| docs/spec/00-how-to-run.md | Starting any session: run order, phase-per-session rules, build model allocation, agent file template |
| docs/spec/01-mission.md | You need the product summary, the two sides, or the launch scope |
| docs/spec/02-existing-repo.md | Touching reminder/, adviser/, tests/, legacy files, hygiene fixes or .env.example |
| docs/spec/03-glossary-roles.md | Naming anything, or checking roles and verification levels (E0/E1/E2) |
| docs/spec/04-principles.md | Before any design decision; these rules override everything else |
| docs/spec/05-subscriptions-billing.md | Plans, entitlements, paywalls, M-Pesa/Paystack, invoices |
| docs/spec/06-feature-modules.md | Building any feature (6.1–6.12) and its acceptance criteria: repository, directory, proposals, provenance, research, trending, ranker, scouts, tracker, emails EM1–EM8, reminders, admin |
| docs/spec/07-ux-information-architecture.md | Any frontend work: navigation, onboarding, empty states, mobile, accessibility, i18n |
| docs/spec/08-architecture-stack-data-model.md | Choosing libraries, schema/migrations, jobs, LLM layer, CI, testing, deploy |
| docs/spec/09-ai-runtime-safety-evals.md | Any runtime LLM call, model choice, injection defences, cost caps, evals |
| docs/spec/10-security-privacy-compliance.md | Personal data, legal templates, Tier-2 access, feature flags, Kenyan compliance |
| docs/spec/11-delivery-phases.md | Planning a phase or checking its exit criteria and release (R1/R2/R3) |
| docs/spec/12-agent-operating-rules.md | Per-task workflow, traceability, ADRs, human gates, when to stop and ask |
| docs/spec/13-open-decisions.md | Writing or checking ADR-001..008 and policy.yaml defaults |
| docs/spec/14-definition-of-done.md | Before marking a task, requirement or the product done; the E2E scenarios |
| docs/spec/appendix-a-traceability.md | Mapping a requirement R01–R53 or R-HYG to its sections and acceptance criteria |

## Build workflow (every phase)
1. Context: query the graphify graph before searching files. Read only the docs/spec/ files the phase needs.
2. Plan: write a short plan for the phase before coding.
3. Build: implement in small steps and commit after each.
4. Test: write tests for every acceptance test ID in the phase. All tests must pass.
5. UI (if the phase has screens): use the frontend-design skill, then the impeccable skill to polish, then Playwright screenshots at 375px and 1440px widths, fixing anything broken.
6. Browser bugs: use chrome-devtools for console, network and performance errors.
7. Review: run ECC's code review on the phase's changes and fix every critical and high issue.
8. Report: write the phase report and update PROGRESS.md.
9. Gate: stop at the phase's gate and wait for human approval.
