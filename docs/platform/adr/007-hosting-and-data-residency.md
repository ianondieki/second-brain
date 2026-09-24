# ADR-007: Hosting, data residency and operations

- Status: PROPOSED (human may veto at G0)
- Date: 2026-09-24
- Spec: docs/spec/08-architecture-stack-data-model.md (Hosting, Storage, Non-functional, Testing & CI, Deploy), docs/spec/10-security-privacy-compliance.md
- Related: ADR-002 (tenancy), ADR-003 (evidence buckets), GATES.md (G1 region, G7 DNS)

## Context

Pilot scale is 10–20 anchor orgs and a few hundred developers; infra budget ≤USD 150/month excluding LLM. Kenyan
data-protection rules and government clients may require local hosting later. Everything must be portable.

## Decision

1. **Region**: AWS `af-south-1` (Cape Town) behind Cloudflare (Nairobi PoP, WAF, DDoS), pending G1 confirmation. Everything is containerised and uses plain Postgres and the S3 API so the stack can move to a Kenyan data centre for government clients without code changes.
2. **Topology**: one `t4g.large` host running Docker Compose (Caddy, web, api, worker, clamav), RDS `db.t4g.small` Postgres 16 with pgvector and PITR (RPO 15 min, 14-day window), S3 buckets `uploads` (presigned, ClamAV in a memory-limited container), `evidence` (Object Lock governance, per-object retention), `backups`, plus the separate encrypted `kyc-review` bucket (no backups, 72 h purge). Terraform in `infra/terraform/`; `make dev` brings up the seeded local stack with Mailpit, MinIO and ClamAV.
3. **Backups and DR**: nightly `pg_dump` encrypted with `age` to an Object-Locked bucket in `eu-west-1` in a separate AWS account; quarterly restore drill logged; RTO 4 h; 99.5% monthly availability target.
4. **Security baseline**: OWASP ASVS L2; TLS everywhere, AES-256 at rest, per-proposal KMS envelope keys for Tier 2; secrets in SSM Parameter Store rotated every 90 days; rate limits (login 5/min/IP+account, API 60/min/user, public search 30/min/IP); CSP nonces, HSTS preload, `X-Frame-Options: DENY`; `gitleaks`, `pip-audit`, `npm audit`, `osv-scanner`, Trivy, CodeQL block on high/critical.
5. **Observability**: structlog JSON without PII, OpenTelemetry to Grafana Cloud free tier, Sentry with PII scrubbing, LLM traces in `llm_calls` (+ optional Langfuse Cloud as a DPA'd sub-processor; never self-hosted in v1), Better Stack uptime on `/healthz` and `/readyz`, healthchecks.io pings from periodic jobs.
6. **CI/CD**: `pr.yml` (lint, types, unit/integration/migration up-down-up + `alembic check`, OpenAPI drift, Playwright against the compose stack, scanners, legacy tests on ubuntu + windows) with an egress-blocked runner; `main.yml` (multi-arch images → GHCR → staging → smoke → production behind a manual-approval Environment; AWS via GitHub OIDC; migrations as a one-off task); `nightly.yml` (LLM evals ≤USD 5, weekly restore test, Renovate). The test-clock router is excluded from the production image at build time (CI asserts 404).
7. **Cross-border transfers**: model providers (US) and AWS `af-south-1` are documented in `docs/legal/lawful_basis.md` and the `/subprocessors` page; the advocate confirms localisation rules before government orgs onboard (G2).

## Alternatives considered

- Kenyan hosting from day one (e.g., local IaaS): rejected for the pilot; no managed Postgres with PITR and Object Lock at comparable cost; the design keeps the move possible.
- Kubernetes: rejected at pilot scale; Compose on one host meets the budget and the RTO.
- Serverless/managed platform (Fly, Render, Vercel): rejected; data residency and Object Lock needs are clearer on AWS, and frontend SSR sits behind the same Caddy.
- Self-hosted observability (Langfuse, Grafana): rejected; needs ClickHouse/Redis and ops time.

## Consequences

- G1 must confirm region, product domain and SMS vendor before Phase 1 deploy config is final; local dev is unaffected.
- Monthly cost target is checked in the Phase 8 report; LLM spend is tracked separately in `llm_calls`.
- Vendor list for G0 pre-approval: AWS, Cloudflare, Postmark, Sentry, Grafana Cloud, Better Stack, healthchecks.io, DigiCert/FreeTSA, SMS vendor, Langfuse Cloud (optional).
