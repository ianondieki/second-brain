# GATES — human sign-offs

Phase 0 output, 2026-09-24. Source: `docs/spec/12-agent-operating-rules.md` (12.4). A gate is signed by the human
editing the **Status** cell of its row to `APPROVED <YYYY-MM-DD>` (optionally with a note), for example
`G0: APPROVED 2026-09-25`. Agents never edit a Status cell. `VETO <date>: <reason>` sends the item back to
`DECISIONS-NEEDED.md`. Until a gate is approved, everything in its "Blocks" column stays blocked.

| Gate | Human provides / approves | Blocks | Inputs recorded in | Status |
|---|---|---|---|---|
| G0 | `PLAN.md`, `REQUIREMENTS.md`, ADR-001..008, `THREAT_MODEL.md`; budget per phase; precision@5 target for AC-PERS-4; pre-approved vendor/free-tier list (Postmark, Sentry, Grafana Cloud, Better Stack, healthchecks.io, Cloudflare, TSA, SMS, Langfuse Cloud) so Phase 8 does not stop per vendor | All product code (Phase 1 start) | `DECISIONS-NEEDED.md` D-01, D-02, D-03; `PLAN.md` §7 | PENDING |
| G1 | Hosting region confirmation (`af-south-1` default, ADR-007), product domain, SMS vendor account | Phase 1 deploy config (`infra/` values); local development is not blocked | `DECISIONS-NEEDED.md` D-10; ADR-007 addendum | PENDING |
| G2 | Advocate-reviewed legal templates (ToS, AUP, Master Enterprise Terms, Evaluation NDA, mutual NDA, EOI, term sheet, assignment, licences, development agreement, acceptance certificate, privacy/cookie/takedown/dispute policies, s.106B certificate, org invitation email and suppression policy, UI claim copy), `docs/legal/esign_exclusions.md`, records custodian, reputation-score formula; agents only insert `[[LEGAL-PLACEHOLDER:<id>]]` | Phase 8 exit; `FEATURE_TIER2_ENABLED` / `FEATURE_DEALS_ENABLED` in production | `docs/legal/`, `legal_templates` table; `DECISIONS-NEEDED.md` D-14 | PENDING |
| G-EVAL | Human labels for the research, scout, ranker and judge gold sets (`docs/spec/09` sizes: research 30, scout 50, judge 20; ranker ≥30 dev/problem pairs) | Phase 4 exit; AC-PERS-4 in Phase 5 | `backend/tests/evals/gold/` (added by the human or pasted for the `test-writer`) | PENDING |
| G3 | Tiers, KES prices, free-tier limits, trial rules (replacing the placeholders in `backend/config/plans.yaml`) | Phase 6 gating values (final); placeholders allow Phase 6 development | `backend/config/plans.yaml`; ADR-006 addendum | PENDING |
| G4 | Daraja shortcode/passkey/keys and Paystack live keys entered directly into SSM by the human | Live payments (may follow launch) | SSM Parameter Store only; never in git or `.env.example` | PENDING |
| G5 | Product name, logo, palette, native-speaker review of `locales/sw.json` | Phase 8 visual polish; Swahili going live; `PRODUCT_NAME` rename (ADR-001) | `frontend/` brand assets; `locales/sw.json` review note | PENDING |
| G6 | Directory seeding policy and list (public organisational information only, starts E0) | Directory going public (production seed); fixtures use `seed/ke_provisional.yaml` before G6 | `backend/seed/` production list; ADR-008 note | PENDING |
| G7 | Sender-domain SPF/DKIM/DMARC (`p=quarantine`) for the Postmark sender domain | Real email to non-test recipients; staging keeps Mailpit until then | Postmark dashboard; `docs/runbooks/email-dns.md` | PENDING |
| G8 | Launch go/no-go after the Phase 8 report (`PROGRESS.md`) | Merge to `main`; production | `PROGRESS.md` Phase 8 report | PENDING |

## How gates interact with phases

- Phase 0 ends at **G0**. Nothing in Phases 1–8 starts before `G0: APPROVED`.
- Phases 1–7 need no gate to exit, except **G-EVAL** at the Phase 4 exit; G1 values are needed only when deploy config is written (Phase 8, or earlier if a staging deploy is requested).
- Phase 8 needs **G2, G5, G6, G7** before it can exit and submits the report for **G8**. **G3** values are needed for Phase 6's final prices; **G4** is needed only for live payments and may follow launch (`docs/spec/11` Release 1 note).
- Reaching any gate is a stop-and-ask condition (`docs/spec/12` 12.5): the orchestrator writes the request in `DECISIONS-NEEDED.md`, finishes unblocked work, and stops.

## Sign-off log

| Gate | Decision | Date | Note |
|---|---|---|---|
| G0 | — | — | awaiting human review of the Phase 0 documents |
