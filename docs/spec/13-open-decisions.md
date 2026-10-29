## 13. Open decisions with defaults (record each as an ADR in Phase 0; the human may veto at G0)

| ADR | Decision | Default |
|---|---|---|
| 001 | Repo layout & product boundary | `docs/spec/02-existing-repo.md` and `docs/spec/08-architecture-stack-data-model.md` repo layout; product placeholder name "Bridge" until G5 |
| 002 | Auth, tenancy & identity providers | `docs/spec/03-glossary-roles.md` roles, `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark` item 8, `docs/spec/08-architecture-stack-data-model.md` Auth/Tenancy |
| 003 | Authorship evidence | `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark` |
| 004 | Email & messaging | `docs/spec/06-feature-modules.md#610-notifications--emails-incl-the-approval-email`, `docs/spec/08-architecture-stack-data-model.md` Email; test mode routes to Mailpit |
| 005 | Runtime LLMs & embeddings | `docs/spec/08-architecture-stack-data-model.md` LLM layer and Embeddings, `docs/spec/09-ai-runtime-safety-evals.md` |
| 006 | Payments | `docs/spec/05-subscriptions-billing.md`; sandbox until G4 |
| 007 | Hosting & data residency | `docs/spec/08-architecture-stack-data-model.md` Hosting and Deploy |
| 008 | Launch scope | `docs/spec/01-mission.md` Launch scope |
| Other defaults | All numeric defaults live in `backend/config/policy.yaml` and are cited by key: stage deadlines per the `docs/spec/06-feature-modules.md#69-kuccps-style-engagement-tracker-state-machine-single-source-of-truth` table (BD); first-contact 5 BD; exclusivity default none / max 90 days; trending half-lives 14/7 days; ranker and scout weights v1; scout `min_fit` 60; rate limits per `docs/spec/08-architecture-stack-data-model.md`; retention per `docs/spec/10-security-privacy-compliance.md`; EM7 07:30 dev / 08:30 org | As stated |
