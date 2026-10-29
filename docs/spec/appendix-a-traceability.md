## Appendix A — Requirement traceability

| R-id | Requirement (short) | Section(s) / AC |
|---|---|---|
| R01 | Extend, don't replace; go beyond reminders | `docs/spec/01-mission.md`, `docs/spec/02-existing-repo.md`, `docs/spec/11-delivery-phases.md` Phase 1, AC-REM-3/4 |
| R02 | Keep daily reminder working and reuse it | `docs/spec/02-existing-repo.md`, `docs/spec/06-feature-modules.md#611-reminders-for-both-sides-reusing-the-reminder-engine`, AC-REM-4 |
| R03 | Production-grade hosted multi-user service | `docs/spec/08-architecture-stack-data-model.md`, `docs/spec/10-security-privacy-compliance.md`, `docs/spec/11-delivery-phases.md` Phase 8, AC-SEC-1..5, `docs/spec/14-definition-of-done.md` item 2 |
| R04 | Connect local developers with orgs having real problems | `docs/spec/01-mission.md`, `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure`–6.3, `docs/spec/06-feature-modules.md#65-research-agent-problems-per-niche--countryregion`, AC-PROP-1, AC-TRACK-4 |
| R05 | Social institutions can join as orgs | `docs/spec/03-glossary-roles.md` Org Type, `docs/spec/05-subscriptions-billing.md` Social Impact, AC-DIR-5/6 |
| R06 | Local (Kenya) context, Safaricom/Airtel, KUCCPS style | `docs/spec/01-mission.md` launch scope, `docs/spec/06-feature-modules.md#62-company-directory-by-niche-claimed-and-unclaimed` seeding, `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth`, ADR-008, AC-DIR-6, AC-PROP-1, AC-REPO-6, AC-TRACK-3 |
| R07 | Developers advertise/publish proposals | `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure`, `docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company`, AC-REPO-4 |
| R08 | Sell proposals to buyers (sale/acquisition flow) | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stages 7–13 (IP terms), AC-TRACK-1/4 |
| R09 | One central repository | `docs/spec/03-glossary-roles.md`, `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure`, AC-REPO-3/5 |
| R10 | Enterprises can browse/search it | `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure` Browse repo, `docs/spec/07-ux-information-architecture.md` Inbox, AC-REPO-3/5 |
| R11 | Companies configure their own agent | `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests`, `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stage 0, AC-SCOUT-1, AC-TRACK-8 |
| R12 | Agent picks by niche and interests | `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests` config, AC-SCOUT-1/5 |
| R13 | Niches incl. micro-finance, schools, universities, governments, NGOs; extendable | `docs/spec/03-glossary-roles.md` Org Type & Niche taxonomy, `docs/spec/08-architecture-stack-data-model.md` `niches`, AC-DIR-5 |
| R14 | Two separate sides with own onboarding/UI | `docs/spec/03-glossary-roles.md`, `docs/spec/07-ux-information-architecture.md` (7.1)–7.3, AC-UX-1 |
| R15 | Different subscriptions per side | `docs/spec/05-subscriptions-billing.md`, AC-SUB-1..5 |
| R16 | Accounts, login, RBAC | `docs/spec/03-glossary-roles.md` roles, `docs/spec/08-architecture-stack-data-model.md` Auth/Tenancy, AC-SEC-1 |
| R17 | Trending Projects view | `docs/spec/06-feature-modules.md#66-trending-problems--trending-projects`, `docs/spec/07-ux-information-architecture.md` Discover, AC-TREND-2 |
| R18 | Trending problems per niche needing solutions | `docs/spec/06-feature-modules.md#66-trending-problems--trending-projects` Opportunity Gap, AC-TREND-2 |
| R19 | Projects linked to the problems they solve | `docs/spec/06-feature-modules.md#66-trending-problems--trending-projects`, AC-REPO-4, AC-TREND-2 |
| R20 | Research agent populates problems | `docs/spec/06-feature-modules.md#65-research-agent-problems-per-niche--countryregion`, AC-RES-1..4 |
| R21 | Scoped by country | `docs/spec/06-feature-modules.md#65-research-agent-problems-per-niche--countryregion` run unit, AC-RES-4 |
| R22 | Scoped by region/county | `docs/spec/06-feature-modules.md#65-research-agent-problems-per-niche--countryregion`, AC-RES-4 |
| R23 | Algorithm personalises what to pursue | `docs/spec/06-feature-modules.md#67-personalisation-ranker-what-to-pursue` (bge-m3 fit + LTR pipeline), AC-PERS-1..5 |
| R24 | Uses research output as input | `docs/spec/06-feature-modules.md#67-personalisation-ranker-what-to-pursue` f5/f6 from Problem cards, AC-PERS-7 |
| R25 | Judges whether worth pursuing | `docs/spec/06-feature-modules.md#67-personalisation-ranker-what-to-pursue` pursuit recommendation + fit labels, AC-PERS-2 |
| R26 | Uses developer's project history | `docs/spec/06-feature-modules.md#67-personalisation-ranker-what-to-pursue` f1/f9 (platform history, opt-in GitHub, reminder stats R2), AC-PERS-3, AC-PERS-6 |
| R27 | Developer picks liked niches | `docs/spec/05-subscriptions-billing.md` liked vs followed, `docs/spec/06-feature-modules.md#67-personalisation-ranker-what-to-pursue` f2, `docs/spec/07-ux-information-architecture.md` (7.3) onboarding, AC-PERS-1 |
| R28 | Connection feature to post a proposal to a target company | `docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company` "Pitch to company", AC-PROP-1 |
| R29 | Proposal = problem + solution pair (developer may paste a new problem) | `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure` Tier 1, `docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company` "Describe a new problem", AC-REPO-4, AC-PROP-5 |
| R30 | Tag several companies on one proposal | `docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company`, AC-PROP-1/2 |
| R31 | Proposals labelled with niche | `docs/spec/06-feature-modules.md#63-proposal-submission-tagging--pitch-to-company` editor, `docs/spec/03-glossary-roles.md` Niche, AC-REPO-4 |
| R32 | Company directory by niche | `docs/spec/06-feature-modules.md#62-company-directory-by-niche-claimed-and-unclaimed`, AC-DIR-1..7 |
| R33 | Company sub-agent checks repo regularly | `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests` schedule, `docs/spec/08-architecture-stack-data-model.md` `scouts.scan`, AC-SCOUT-6 |
| R34 | Sub-agent emails the PM team | `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests` digest, EM3, AC-SCOUT-1 |
| R35 | Enterprise sets digest recipients | `docs/spec/06-feature-modules.md#68-enterprise-scout-agents--email-digests` config `recipients[]`, AC-SCOUT-7 |
| R36 | Enterprise approves or declines | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stages 0/3, `DECLINED`, AC-TRACK-4/8 |
| R37 | Company contacts idea owner via platform | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stages 3–4, Messages tab, AC-TRACK-9, AC-MAIL-1/2 |
| R38 | Implementation arrangements recorded | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stages 7–9 milestones/terms, AC-TRACK-6/10 |
| R39 | Idea carries owner proof (owner attribution mark on every render) | `docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure` marks, `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark` disclosure record + certificate, AC-REPO-2, AC-IP-1 |
| R40 | Tamper-evident, timestamped authorship (honest version of "theft-proof") | `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark` (why: Copyright Act protects expression, not ideas), AC-IP-2/3/4 |
| R41 | Court-usable, exportable record | `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark`, `docs/spec/06-feature-modules.md#612-admin-moderation--disputes` evidence pack + s.106B, AC-ADM-2 |
| R42 | Tracker covers acceptance → implementation → finish → signing | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` main path, AC-TRACK-1/4 |
| R43 | Formal signing stage | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` stages 8, 11; `SignatureProvider`; AC-TRACK-4/10 |
| R44 | Visual KUCCPS-style tracker | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` rendering, `docs/spec/07-ux-information-architecture.md`, AC-TRACK-3/4 |
| R45 | Endorsement by each party per stage | `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` dual-endorsement rows, AC-TRACK-3 |
| R46 | Full transparency to both parties | `docs/spec/04-principles.md` (4.7), `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` History tab, AC-TRACK-3 |
| R47 | Developer daily reminders on active projects | `docs/spec/06-feature-modules.md#611-reminders-for-both-sides-reusing-the-reminder-engine`, AC-REM-1/3 |
| R48 | Enterprise progress reminder | `docs/spec/06-feature-modules.md#611-reminders-for-both-sides-reusing-the-reminder-engine` org digest, EM7, AC-REM-2 |
| R49 | Reminders state on-track vs agreed terms | `docs/spec/06-feature-modules.md#611-reminders-for-both-sides-reusing-the-reminder-engine` health rules vs signed milestones, AC-REM-1/3 |
| R50 | Email on approval | `docs/spec/06-feature-modules.md#610-notifications--emails-incl-the-approval-email` EM2, AC-MAIL-1 |
| R51 | Email says company will contact shortly | `docs/spec/06-feature-modules.md#610-notifications--emails-incl-the-approval-email` EM2 body, AC-MAIL-1 |
| R52 | Uncluttered UI | `docs/spec/04-principles.md` (4.6), `docs/spec/07-ux-information-architecture.md`, AC-UX-1/2/5 |
| R53 | Easy to navigate, user-friendly | `docs/spec/07-ux-information-architecture.md`, AC-UX-3/4 |
| R-HYG-01..06 | Channel flip-flop, stale Evolution vars, retired Groq model, TZ Lagos→Nairobi, duplicate docs/10, stray .code-workspace | `docs/spec/02-existing-repo.md`, `docs/spec/11-delivery-phases.md` Phase 1, AC-HYG-01..06 (one CI grep assertion each) |
