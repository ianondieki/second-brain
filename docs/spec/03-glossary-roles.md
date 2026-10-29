## 3. Glossary & roles

Use exactly these terms in code, UI and docs.

| Term | Meaning |
|---|---|
| **Problem** | A stated real-world problem card: niche, region, statement, cited evidence, source (`research_agent` / `org_brief` / `developer`), trend score. |
| **Problem Brief** | A Problem posted by a verified organisation inviting proposals. |
| **Proposal** | A developer's structured problem–solution pair, linked to ≥1 Problem. Has tiered content (`docs/spec/06-feature-modules.md#61-central-repository--tiered-disclosure`). Versions are immutable. |
| **Central Repository** | The searchable set of published Proposals (teasers) and Problems. |
| **Organisation (Org)** | Any enterprise-side entity. Axis 1 **Org Type**: Company, SME, SACCO/MFI, University/TVET, School, National Govt, County Govt, NGO/PBO, Development Partner. Axis 2 **Niche**: two-level taxonomy mapped to ISIC Rev.4 (Financial services › Microfinance & SACCOs; ICT › Networks & Telecommunications; Education › Higher education / Basic education; Public sector › National government / County government; Health; Agriculture; Energy; Logistics; Retail; Social/NGO; …). Extendable by admin. |
| **Directory** | All Orgs, `E0 unclaimed` / `E1 domain-verified` / `E2 legal-entity-verified`, grouped by niche, filterable by org type and county. "Claimed" = E1 or E2. An E1 org sees only the count and niches of tags held for it (`held_pending_verification`); engagements, Tier 2 and every tracker stage require E2. |
| **Tag** | A Proposal directed at a specific Org. Visible only to the owner; each tagged org sees its own tag only; never shown publicly, in search facets, badges, scout rationales or Browse. |
| **Engagement** | One Proposal × one Org (key `proposal_id, org_id`; pinned to the version first disclosed, later versions recorded as a `version_shared` event). Carries the stage tracker. A proposal tagged to 5 telecoms has 5 engagements. |
| **Endorsement** | One party's signed-off decision at a dual-endorsement stage (the KUCCPS releasing/receiving analogue). |
| **Scout Agent** | An Org's form-configured matcher that scans the repository on a schedule and emails a digest. Read-only, no tools. |
| **Research Agent** | Scheduled agent that populates cited Problems per niche × country/region, published only after moderator approval. |
| **Disclosure Record** | Per registered version: canonical manifest, SHA-256, server signature, RFC 3161 token, certificate. |
| **Region** | Country › County. MVP: KE + 47 counties; supra-national (EAC) in Release 3. |

**Roles.** Developer (D0–D3 verification, `docs/spec/06-feature-modules.md#64-authorship-provenance--watermarking-the-honest-watermark`). Org members: `owner`, `admin`, `reviewer` (the PM team: receives digests, evaluates under NDA, shortlists, may *Recommend* internally without changing state), `signatory` (only role that can Approve to proceed, express interest at stage 0, sign, endorse closure), `finance`, `viewer`. Platform staff: `admin` (claims, directory, plans, refunds, research approval, feature flags), `moderator` (moderation queue, disputes, takedowns), `support` (read-only; impersonation off by default, always audited).
