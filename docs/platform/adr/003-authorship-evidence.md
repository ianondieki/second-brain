# ADR-003: Authorship evidence (the honest "watermark")

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/06-feature-modules.md (6.4), docs/spec/04-principles.md (4.2), docs/spec/10-security-privacy-compliance.md
- Related: ADR-002 (verification levels), ADR-007 (Object Lock buckets), THREAT_MODEL.md (Provenance, Idea leakage)

## Context

The original request asked for "theft-proof" ideas. No software can prevent idea theft and the Copyright Act 2001
protects expression, not ideas. The buildable version is evidence + controlled disclosure + traceability + a
dispute path.

## Decision

1. **Registration on publish** (drafts are not evidence): RFC 8785 canonical JSON manifest of all Tier-1/2 fields, attachment SHA-256s, salted owner refs, attestation ids, `prev_version_hash`, optional commit SHAs → `content_hash = SHA-256(manifest)` → Ed25519 server signature (key in KMS, public keys at `/.well-known/provenance-keys.json`) → RFC 3161 timestamp (`TSA_URL` configurable; DigiCert primary, FreeTSA fallback; "Timestamp pending" until stored) → `proposal.version_registered` audit event. Each step is an idempotent background job. OpenTimestamps proofs and the hourly upgrade job are Release 2.
2. **Certificate PDF** per version generated on demand (never stored under Object Lock), with the fixed footer "This certificate is evidence of what was submitted and when. It is not a patent, copyright registration or guarantee against independent development or misuse." Public `/verify/{cert_id}` shows hash, timestamp, TSA serial and match/no-match only, unless the owner opts to show name and title.
3. **Controlled disclosure**: Tier 2 released only through `can_view_tier2` (ADR-002), per-person Evaluation NDA with template hash, per-viewer visible tiled overlay + metadata `view_id` + access log in Release 1; invisible text/image marks in Release 2. Trace tool staff-only inside an open dispute; output is "probable match", never "proof".
4. **Append-only chains**: `audit_events` and `engagement_events` are hash-chained (`prev_hash`/`event_hash`), INSERT-only via triggers and grants, serialised with `pg_advisory_xact_lock(chain_id)`; personal or free text lives in mutable `event_details` so erasure never breaks the chain. Hourly RFC 3161 anchor of chain heads; nightly verification publishes a signed Merkle root to `/transparency`.
5. **Dispute path**: prior-knowledge declaration window (10 BD after first Tier-2 access), evidence pack (versions, manifests, proofs, access-log extract with chain proof, NDA acceptances, watermark trace, declarations, EOIs, stage history, messages, signed documents) hashed and TSA-stamped, with an unsigned Evidence Act s.106B certificate signed on request by the records custodian named at G2. The platform never rules on legal ownership; sanctions are labelled platform-policy.
6. **Language**: banned-claims lint (`copy/banned_claims.txt`) fails CI on "theft-proof", "cannot be stolen", "protected idea", "patented" and on "Approve/approved" without a non-binding qualifier in `engagement.*`, `tracker.*`, `email.em2.*` (AC-IP-4, principle 4.2).

## Alternatives considered

- Blockchain anchoring as the primary proof: rejected for Release 1; RFC 3161 tokens are verifiable offline with `openssl ts -verify`, understood in electronic-evidence practice, and cheap. OpenTimestamps is added in Release 2 as a second, independent anchor.
- Storing certificate PDFs immutably: rejected; names are resolved at render time so erasure and D2 legal-name updates stay possible.
- Client-side hashing only: rejected; the server signature and TSA are what make the record tamper-evident.
- DRM/"no copy" viewers: rejected; screenshots defeat them, and they harm accessibility; watermark + log + NDA is the honest control.

## Consequences

- Any change to manifest fields is a new manifest version with its own hash; the canonicalisation code is frozen by golden fixtures (AC-IP-1).
- `evidence` bucket uses Object Lock (governance) with retention from the `docs/spec/10` schedule; packs are pseudonymised with a separately held key map (AC-IP-7).
- Marketing and UI copy must use the approved phrasing from principle 4.2; legal review of the s.106B certificate template happens at G2.
