# Phase 1 version research (T1.3)

Date checked: 2026-09-24 (UTC). All values verified live against the registry/API listed in
each "Verified via" column on that date; no value is carried over from training data. Where a
source did not state a fact, the row says "not documented" instead of guessing.

## 1. Next.js (D-08 — pin exactly, ADR-001 addendum)

| Claim | Quote / value | URL | Verified via | Date |
|---|---|---|---|---|
| npm `latest` dist-tag | `"latest":"16.3.6"` | https://registry.npmjs.org/next | npm registry JSON, `dist-tags.latest` | 2026-09-24 |
| Major version | 16 | https://registry.npmjs.org/next | same JSON, version string of dist-tags.latest | 2026-09-24 |
| Minimum Node.js (`engines.node`) | `"engines":{"node":">=20.9.0"}` on version 16.3.6 | https://registry.npmjs.org/next | npm registry JSON, `versions["16.3.6"].engines` | 2026-09-24 |
| Next 16.3.6 peer deps | `"react":"^18.2.0 || 19.0.0-rc-de68d2f4-20241204 || ^19.0.0"`, `"react-dom"` same range, `"@playwright/test":"^1.51.1"` (optional, `peerDependenciesMeta.@playwright/test.optional=true`), `"babel-plugin-react-compiler":"*"` (optional), `"@opentelemetry/api":"^1.1.0"` (optional) | https://registry.npmjs.org/next | npm registry JSON, `versions["16.3.6"].peerDependencies` / `.peerDependenciesMeta` | 2026-09-24 |
| Matching `eslint-config-next` | `"latest":"16.3.6"` (same version number as `next`) | https://registry.npmjs.org/eslint-config-next | npm registry JSON, `dist-tags.latest` | 2026-09-24 |
| `eslint-config-next` peer range | `"peerDependencies":{"eslint":">=9.0.0","typescript":">=3.3.1"}` | https://registry.npmjs.org/eslint-config-next | npm registry JSON, `versions["16.3.6"].peerDependencies` | 2026-09-24 |

**Implication for D-08 / ADR-001:** pin `"next": "16.3.6"` and `"eslint-config-next": "16.3.6"` exactly
(no caret), and set the frontend Docker/CI Node base image to Node ≥20.9.0 — but see §5/§7 below:
GitHub-hosted Actions runners moved to Node 24 by default on 2026-06-16 and Node 20 was removed
from Actions entirely on 2026-09-23, so the CI Node version is already ≥24, comfortably above
Next's floor.

## 2. Other npm packages — latest stable (dist-tags.latest)

| Package | Latest | engines / notable peer | URL | Verified via | Date |
|---|---|---|---|---|---|
| react | 19.3.0 | `engines.node:">=0.10.0"` (unchanged floor) | https://registry.npmjs.org/react | npm registry JSON | 2026-09-24 |
| react-dom | 19.3.0 | `peerDependencies.react:"^19.3.0"` — react-dom pins react to its own exact minor | https://registry.npmjs.org/react-dom | npm registry JSON | 2026-09-24 |
| typescript | 7.0.2 | `engines.node:">=16.20.0"`; dist-tags also show `"next":"7.1.0-dev...","rc":"7.0.1-rc"` — 7.0.2 is the first stable line of the rewritten (Go-based "native") compiler; this is a **major architecture change from the 5.x line**, flag for review before pinning | https://registry.npmjs.org/typescript | npm registry JSON, `dist-tags` + `versions["7.0.2"]` | 2026-09-24 |
| tailwindcss | 4.3.3 | `engines`: not documented (field absent in package.json) | https://registry.npmjs.org/tailwindcss | npm registry JSON | 2026-09-24 |
| @tailwindcss/postcss | 4.3.3 | matches tailwindcss version | https://registry.npmjs.org/@tailwindcss/postcss | npm registry JSON | 2026-09-24 |
| next-intl | 4.14.7 | `peerDependencies.react:"^16.8.0 \|\| ^17.0.0 \|\| ^18.0.0 \|\| >=19.0.0-rc <19.0.0 \|\| ^19.0.0"` — compatible with react 19.3.0 | https://registry.npmjs.org/next-intl | npm registry JSON | 2026-09-24 |
| openapi-typescript | 7.13.0 | `engines`: not documented | https://registry.npmjs.org/openapi-typescript | npm registry JSON | 2026-09-24 |
| openapi-fetch | 0.17.0 | `engines`: not documented | https://registry.npmjs.org/openapi-fetch | npm registry JSON | 2026-09-24 |
| vitest | 5.0.1 | `engines.node:"^22.12.0 \|\| ^24.0.0 \|\| >=26.0.0"` — **excludes Node 20**; dev/CI containers must run Node ≥22.12 | https://registry.npmjs.org/vitest | npm registry JSON | 2026-09-24 |
| @playwright/test | 1.63.0 | `engines.node:">=20"`; satisfies Next's optional peer range `^1.51.1` | https://registry.npmjs.org/@playwright/test | npm registry JSON | 2026-09-24 |
| @axe-core/playwright | 4.13.0 | `peerDependencies.playwright-core:">= 1.0.0"` | https://registry.npmjs.org/@axe-core/playwright | npm registry JSON | 2026-09-24 |
| eslint | 10.11.0 | `engines.node:"^20.19.0 \|\| ^22.13.0 \|\| >=24"` | https://registry.npmjs.org/eslint | npm registry JSON | 2026-09-24 |
| @types/react | 19.3.0 | matches react 19.3.0 | https://registry.npmjs.org/@types/react | npm registry JSON | 2026-09-24 |
| @types/node | 26.6.2 | dist-tags show a `ts6.0` alias also at `26.6.2` | https://registry.npmjs.org/@types/node | npm registry JSON | 2026-09-24 |

**Peer-dependency note (next × react):** Next 16.3.6 requires react/react-dom `^19.0.0` (or the
listed 19 RC build) — the 18.x line is also accepted by the range string but react's own latest
is 19.3.0, so a fresh install resolves to react 19.3.0 + react-dom 19.3.0, which satisfies both
next's peer range and react-dom's own `^19.3.0` peer on react. No conflict found.

## 3. shadcn/ui CLI vs Next 16 + Tailwind v4

| Claim | Quote | URL | Verified via | Date |
|---|---|---|---|---|
| shadcn CLI latest | `"latest":"4.21.0"`, `engines.node:">=20.18.1"` | https://registry.npmjs.org/shadcn | npm registry JSON | 2026-09-24 |
| Tailwind v4 support | "The CLI can now initialize projects with Tailwind v4"; "All components are updated for Tailwind v4 and React 19"; "Your existing apps with Tailwind v3 and React 18 will still work" | https://ui.shadcn.com/docs/tailwind-v4 | WebFetch of the page | 2026-09-24 |
| Next.js 16 explicitly named | Not documented — the Next.js installation page (https://ui.shadcn.com/docs/installation/next) names no Next.js version number and does not mention Tailwind v4 | https://ui.shadcn.com/docs/installation/next | WebFetch of the page | 2026-09-24 |

**One-line answer:** shadcn/ui's docs confirm Tailwind v4 + React 19 support but do not name
Next.js 16 anywhere; since Next 16.3.6 requires react `^19.0.0` (§1) and shadcn only requires
Node ≥20.18.1 (below Next's ≥20.9.0 floor is not a conflict — 20.18.1 is the stricter number),
compatibility is inferred, not officially stated — treat as **UNVERIFIED for Next 16 specifically**
and re-check after `create-next-app` + `shadcn init` in Phase 1 build.

## 4. PyPI latest stable + requires_python

All fetched from `https://pypi.org/pypi/<name>/json` → `info.version` / `info.requires_python`,
verified 2026-09-24. **None of the floors below exceed 3.12**, so every package supports Python
3.12 (the backend interpreter per docs/spec/08).

| Package | Latest | requires_python | Python 3.12 OK? |
|---|---|---|---|
| fastapi | 0.141.1 | >=3.10 | yes |
| pydantic | 2.13.5 | >=3.9 | yes |
| pydantic-settings | 2.15.0 | >=3.10 | yes |
| sqlalchemy | 2.0.54 | >=3.7 | yes |
| alembic | 1.20.0 | >=3.10 | yes |
| psycopg | 3.3.6 | >=3.10 | yes |
| psycopg-binary | 3.3.6 | >=3.10 | yes (summary: "PostgreSQL database adapter for Python -- C optimisation distribution") |
| procrastinate | 3.10.0 | >=3.10 | yes |
| structlog | 26.1.0 | >=3.10 | yes |
| argon2-cffi | 25.1.0 | >=3.8 | yes |
| pyotp | 2.10.0 | >=3.8 | yes |
| itsdangerous | 2.2.0 | >=3.8 | yes |
| httpx | 0.28.1 | >=3.8 | yes |
| respx | 0.23.1 | >=3.8 | yes |
| jinja2 | 3.1.6 | >=3.7 | yes |
| uvicorn | 0.53.0 | >=3.10 | yes |
| pytest | 9.1.1 | >=3.10 | yes |
| pytest-asyncio | 1.4.0 | >=3.10 | yes |
| hypothesis | 6.168.1 | >=3.10 | yes |
| testcontainers | 4.15.0 | >=3.10 | yes |
| mypy | 2.3.1 | >=3.10 | yes |
| ruff | 0.16.8 | >=3.7 | yes |
| pip-audit | 2.10.1 | >=3.10 | yes |
| pyyaml | 6.0.3 | >=3.8 | yes |
| types-PyYAML | 6.0.12.20260906 | >=3.10 | yes |
| email-validator | 2.3.0 | >=3.8 | yes |
| python-multipart | 0.0.32 | >=3.10 | yes |

Source URL pattern for every row: `https://pypi.org/pypi/<package>/json`. Verified via PyPI JSON API on 2026-09-24.

## 5. GitHub Actions — current major tags and Node-runtime status

| Action | Latest tag | Pin as | URL | Verified via | Date |
|---|---|---|---|---|---|
| actions/checkout | v7.0.1 | `@v7` | https://github.com/actions/checkout/releases.atom | Atom releases feed (`<entry><title>/<updated>`) | 2026-09-24 |
| actions/setup-python | v7.0.0 | `@v7` | https://github.com/actions/setup-python/releases.atom | Atom releases feed | 2026-09-24 |
| actions/setup-node | v7.0.0 | `@v7` | https://github.com/actions/setup-node/releases.atom | Atom releases feed | 2026-09-24 |
| astral-sh/setup-uv | v10.2.0 | `@v10` | https://github.com/astral-sh/setup-uv/releases.atom | Atom releases feed | 2026-09-24 |
| github/codeql-action | v4.38.2 (v3.38.2 line also still published same day) | `@v4` | https://github.com/github/codeql-action/releases.atom | Atom releases feed | 2026-09-24 |
| actions/upload-artifact | v7.0.1 | `@v7` | https://github.com/actions/upload-artifact/releases.atom | Atom releases feed | 2026-09-24 |

**Node runtime status:** "Node.js 20 is no longer available in GitHub Actions" — runners removed
Node 20 entirely on 2026-09-23; GitHub-hosted runners switched to Node 24 by default on
2026-06-16, with a March 2026 phase-in starting 2026-03-04. The `actions/setup-python` v7 and
`actions/setup-node` v7 releases used above are explicitly the "Migrate to ESM and upgrade
dependencies" majors that move off Node 20. All six actions above are therefore on the
Node-24-compatible major as of the check date.

Source: [Node 20 is no longer available in GitHub Actions – GitHub Changelog](https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/) and [Deprecation of Node 20 on GitHub Actions runners – GitHub Changelog](https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/), read via WebSearch summary on 2026-09-24 (changelog pages themselves not directly fetched — treat exact wording as paraphrase, not a verbatim quote; re-confirm by opening the changelog URL directly before relying on exact phrasing).

## 6. Scanners — container tags and the trivy-action supply-chain compromise

| Tool | Latest release / image tag | URL | Verified via | Date |
|---|---|---|---|---|
| gitleaks | `v8.30.1` (binary release and `ghcr.io/gitleaks/gitleaks:v8.30.1` — tag confirmed present in registry) | https://github.com/gitleaks/gitleaks/releases.atom ; https://ghcr.io/v2/gitleaks/gitleaks/tags/list | Atom feed + ghcr.io anonymous-token `tags/list` API | 2026-09-24 |
| osv-scanner | `v2.6.0` (`ghcr.io/google/osv-scanner:v2.6.0` — tag confirmed present, 178 tags total) | https://github.com/google/osv-scanner/releases.atom ; https://ghcr.io/v2/google/osv-scanner/tags/list | Atom feed + ghcr.io `tags/list` API | 2026-09-24 |
| Trivy | `v0.74.0` (`ghcr.io/aquasecurity/trivy:0.74.0` — tag confirmed present, 745 tags total) | https://github.com/aquasecurity/trivy/releases.atom ; https://ghcr.io/v2/aquasecurity/trivy/tags/list | Atom feed + ghcr.io `tags/list` API | 2026-09-24 |

**Security advisory — use the container image, not `aquasecurity/trivy-action`/`setup-trivy` as a
floating tag:** GHSA-69fq-xp46-6x23 / CVE-2026-33634 (critical, CVSS 9.4), published 2026-03-21:
"On March 19, 2026, a threat actor used compromised credentials to publish a malicious Trivy
v0.69.4 release" and force-pushed malicious commits onto version tags of
`aquasecurity/trivy-action` (all tags `<0.35.0`, exposure window ~2026-03-19 17:43 UTC to
2026-03-20 05:40 UTC, ~12 hours) and `aquasecurity/setup-trivy` (all tags `<0.2.6`, ~4 hours).
Fixed action versions are `trivy-action >=0.35.0` and `setup-trivy >=0.2.6`; the advisory also
notes DockerHub-published `0.69.5`/`0.69.6` images were briefly compromised on 2026-03-22–23.
This was reported as the **second** trivy-ecosystem compromise within three weeks (first
incident ~2026-02-28, containment of which was later found incomplete).

Source: [GHSA-69fq-xp46-6x23](https://github.com/advisories/GHSA-69fq-xp46-6x23), read via WebFetch 2026-09-24.

**Recommendation:** pull `ghcr.io/aquasecurity/trivy:0.74.0` (or gitleaks/osv-scanner images
above) directly by tag **and pin by digest** (`ghcr.io/…@sha256:<digest>`) in CI rather than using
the `aquasecurity/trivy-action` or `aquasecurity/setup-trivy` GitHub Actions, even on patched
tags — the repo has now had two credential-stealing supply-chain compromises in 2026 and mutable
Action tags were the attack vector both times. If an Action wrapper is wanted for log formatting,
pin it to a commit SHA (not a version tag) per the advisory's own remediation advice: "Pin GitHub
Actions to commit SHAs rather than mutable version tags to prevent future hijacking."

## 7. Docker images (dev stack)

| Image | Finding | URL | Verified via | Date |
|---|---|---|---|---|
| `pgvector/pgvector:pg16` | Tag exists; `pg16` currently resolves to `0.8.6-pg16` (`pg16-bookworm` base), last pushed 2026-08-13T21:26:00Z | https://hub.docker.com/v2/repositories/pgvector/pgvector/tags | Docker Hub v2 tags API | 2026-09-24 |
| `axllent/mailpit` latest | `latest` tag present, currently `v1.31.2`, last pushed 2026-09-19T11:32:22Z; a rolling `v1` and `v1.31` tag also exist | https://hub.docker.com/v2/repositories/axllent/mailpit/tags | Docker Hub v2 tags API | 2026-09-24 |
| `minio/minio` | **Repository returns `{"message":"object not found"}` from the Docker Hub v2 API** — confirms the image is gone from Docker Hub, matching third-party reports that MinIO ended pre-compiled community-edition binary/container releases around 2025-10-23 and stopped publishing new tags | https://hub.docker.com/v2/repositories/minio/minio/tags (API call, direct evidence); corroborating third-party reports found via WebSearch (not MinIO's own primary announcement — that page was not located/fetched) | Docker Hub v2 tags API (primary) + WebSearch summaries (secondary, unverified primary source) | 2026-09-24 |
| `clamav/clamav` latest stable | `stable` and `stable-debian13-slim`/`stable-debian` tags present; currently pinned to `1.5.4` (`1.5.4-debian13-slim` / `1.5.4-debian`), last pushed 2026-09-21T07:17Z | https://hub.docker.com/v2/repositories/clamav/clamav/tags | Docker Hub v2 tags API | 2026-09-24 |

**MinIO recommendation:** do not add `minio/minio` to `make dev` — the Docker Hub API call
above returned "object not found" directly (primary evidence the repository/tags are gone), which
is consistent with (but not proven by) secondary reporting that MinIO discontinued free
container/binary releases in Q4 2025. **Open question / re-verify before Phase 1 build:** find
MinIO's own primary-source statement (e.g. an official blog post or GitHub release note) rather
than relying on aggregator blogs; until that is found, treat the discontinuation reason as
"reported, not confirmed by MinIO directly." Candidate replacements for the dev stack, cited only
as names, not yet version-verified: SeaweedFS, RustFS, Garage (S3-compatible, actively
maintained per WebSearch results) — **pick and verify one in a follow-up research pass before
committing infra/ changes.**

## 8. uv

| Claim | Quote / value | URL | Verified via | Date |
|---|---|---|---|---|
| Latest uv version | `0.12.18`, released 2026-09-23T14:29:08Z | https://github.com/astral-sh/uv/releases.atom | Atom releases feed | 2026-09-24 |
| Install Python 3.12 via uv | `uv python install 3.12` | https://docs.astral.sh/uv/guides/install-python/ | WebFetch of the official uv docs page | 2026-09-24 |

## Open questions

1. shadcn/ui docs never name Next.js 16 explicitly (§3) — re-verify compatibility empirically once
   `create-next-app@16.3.6` + `shadcn init` run in the Phase 1 worktree.
2. TypeScript 7.0.2 is a new major built on the Go-native compiler, a significant jump from the
   5.x line most current tooling (eslint plugins, ts-node, etc.) was written against (§2) — confirm
   `eslint-config-next`, `openapi-typescript`, and any `typescript-eslint` version pinned actually
   supports TS 7 before pinning it as the repo's compiler; consider pinning TS 5.x instead if any
   tool in the chain does not yet support 7.x (not checked here — out of scope of this pass).
3. MinIO discontinuation (§7): no MinIO-authored primary source was fetched, only Docker Hub API
   evidence (repository not found) plus secondary blog corroboration. Find and cite MinIO's own
   statement, and get a second opinion on which replacement (SeaweedFS / RustFS / Garage) best
   fits `make dev`'s footprint before infra/ work starts.
4. GitHub's own changelog posts for Node 20 deprecation (§5) were read through WebSearch's summary
   feature, not fetched and quoted directly — re-open
   https://github.blog/changelog/2026-09-23-node-20-is-no-longer-available-in-github-actions/ and
   quote the exact wording before citing it in an ADR.
5. `docs/spec/08-architecture-stack-data-model.md` should be checked against §1 pin
   recommendations (Next 16.3.6 exact pin, Node ≥24 in CI) to see if it already commits to a
   different Next major — flag to the orchestrator as a possible spec/ADR conflict if so (not
   checked in this pass — out of scope for a read-only research note).
