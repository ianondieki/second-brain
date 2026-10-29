# Public demo hosting at zero spend: Hugging Face Spaces vs GitHub Codespaces (and four others)

Read on 2026-10-13. All pages below were read on that date; "not stated" means the page read is silent.

## Question

Can the owner get a durable, public, anyone-can-open link to the all-in-one Bridge demo container (about 1 GB peak, one port, Postgres inside, nightly reset) at zero spend (D-36), needing at most a free account?

## Short answer

1. **Hugging Face Docker Spaces no longer fit "zero spend".** The Hub docs now say Docker Spaces on free `cpu-basic` need a PRO subscription (USD 9/month) to create. Free accounts get Static Spaces only. Technically it would fit (2 vCPU, 16 GB, 50 GB ephemeral disk, uid 1000, `app_port`, `*.hf.space`), so it is a spend decision for the owner, not a technical blocker.
2. **GitHub Codespaces is free but not durable.** It idles out (default 30 min, max 4 h) and a stopped codespace serves nothing. It suits a short live demo, not a standing link.
3. **No other free tier reviewed fits a ~1 GB container without a card or spend.** Render and Koyeb free are 512 MB, Fly has no free tier, and Oracle Always Free (12 GB Arm) needs a card for sign-up.
4. Recommendation: see the last section. Escalate to the owner as a D-36 decision.

## Evidence

### 1. Hugging Face Spaces (Docker SDK, CPU basic)

| Claim | Quote | URL |
|---|---|---|
| Docker Spaces need a paid plan to create | "Gradio and Docker Spaces run on compute and require a paid plan to create: PRO for personal accounts, Team or Enterprise for organizations." | https://huggingface.co/docs/hub/spaces-overview |
| Same, with the failure mode | "Without a subscription, creating, duplicating or moving a Gradio or Docker Space on `cpu-basic` fails with a payment error (HTTP 402)." | https://huggingface.co/docs/huggingface_hub/main/en/guides/manage_spaces |
| PRO price and scope | "$9 /month"; "Host your own ZeroGPU, Gradio & Docker Spaces on compute" | https://huggingface.co/pricing |
| Looks recent (July 2026), unannounced | Forum thread of 2026-07-08: Docker SDK "marked as Paid"; UI prompt on 2026-07-24 "to unlock Docker Spaces". No staff reply. | https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580 |
| Static Spaces are free (not usable for this stack) | "Static Spaces are free for everyone." | https://huggingface.co/docs/hub/spaces-overview |
| CPU basic size | "CPU Basic \| 2 vCPU \| 16 GB \| - \| 50 GB \| Free!" | https://huggingface.co/docs/hub/spaces-gpus |
| Disk is ephemeral | "This disk space is ephemeral, meaning its content will be lost if your Space restarts or is stopped." Also "The data written on disk is lost whenever your Docker Space restarts." Persistence needs a Storage Bucket. | https://huggingface.co/docs/hub/spaces-storage ; https://huggingface.co/docs/hub/spaces-sdks-docker |
| Sleep | "it will go to sleep if inactive for more than a set time (currently, 48 hours). Anyone visiting your Space will restart it automatically." Custom sleep time needs paid hardware. | https://huggingface.co/docs/hub/spaces-gpus |
| Build time / image size limits | Not stated on the pages read. Only `startup_duration_timeout`: "Defaults to 30 minutes". | https://huggingface.co/docs/hub/spaces-config-reference |
| User and writable dirs | "The container runs with user ID 1000." Create the user and `WORKDIR` before `COPY`; example `RUN mkdir -p /data` + `chmod 777 /data`. A complete list of writable directories is not stated. `/data` (bucket volume) "is only available at runtime". | https://huggingface.co/docs/hub/spaces-sdks-docker |
| `app_port` | "**`app_port`** : _int_ Port on which your application is running. Used only if `sdk` is `docker`. Default port is `7860`." (README YAML, with `sdk: docker`) | https://huggingface.co/docs/hub/spaces-config-reference |
| Multiple ports | "a workaround is to use a reverse proxy like Nginx to dispatch requests ... on a single port" | https://huggingface.co/docs/hub/spaces-sdks-docker |
| Outbound network | "standard HTTP and HTTPS ports (80 and 443) along with port 8080. Any requests going to other ports will be blocked." | https://huggingface.co/docs/hub/spaces-overview |
| Content policy | Not ML-only in text: describes the Hub as hosting "Models, Datasets, and Machine Learning Applications"; no rule against non-ML apps; prohibits "Hosting excessive or irrelevant data in repositories". Not explicitly allowed either. | https://huggingface.co/content-policy |
| Public Space exposes source | "**Public** Spaces are fully open: anyone can view the source code, access the running app, and clone the repository." Protected (hides source) is PRO/Team/Enterprise. | https://huggingface.co/docs/hub/spaces-overview |
| URL format | "`https://<space-subdomain>.hf.space`" | https://huggingface.co/docs/hub/spaces-embed |
| Iframe on huggingface.co | The `huggingface.co/spaces/<user>/<app>` page contains the app "hosted on a different domain (`*.hf.space`) within an iframe"; browsers restrict third-party cookies in it. Opening `*.hf.space` directly is first-party. X-Frame-Options / CSP `frame-ancestors`: not stated; `disable_embedding` ("Defaults to false, i.e. Spaces *can* be embedded") is the documented switch. | https://huggingface.co/docs/hub/spaces-cookie-limitations ; https://huggingface.co/docs/hub/spaces-config-reference |
| Variables / secrets | Variables: build-time as `build-arg`s, runtime as env. Secrets: runtime as env; build-time via `RUN --mount=type=secret,id=NAME,mode=0444,required=true` reading `/run/secrets/NAME`. Set in Space Settings or API `add_space_secret` / `add_space_variable`. Variables are public. Changing them "will trigger a restart". | https://huggingface.co/docs/hub/spaces-sdks-docker ; .../guides/manage_spaces |
| GitHub Actions push | Official action `huggingface/hub-sync@v0.3.0` with secret `HF_TOKEN` (inputs `github_repo_id`, `huggingface_repo_id`, `hf_token`, `space_sdk`); it uses `hf repos create` + `hf upload`. Alternative: `git push https://HF_USERNAME:$HF_TOKEN@huggingface.co/spaces/HF_USERNAME/SPACE_NAME main`. | https://huggingface.co/docs/hub/spaces-github-actions |
| Token type | `write` role: "grant write access to the repositories you have write access to"; `fine-grained` recommended for production. OIDC "Trusted Publishers" can replace a stored token. Minimum scope for Space push: not stated. | https://huggingface.co/docs/hub/security-tokens |
| Restart / factory rebuild by API | `restart_space(repo_id, token=None, factory_reboot=False)`; "factory_reboot ... the Space will be rebuilt from scratch without caching any requirements"; calls `POST {endpoint}/api/spaces/{repo_id}/restart`; "only the owner of a Space can restart it". | https://huggingface.co/docs/huggingface_hub/main/en/package_reference/hf_api ; source `src/huggingface_hub/hf_api.py` (github.com/huggingface/huggingface_hub) |

### 2. GitHub Codespaces (personal account)

| Claim | Quote | URL |
|---|---|---|
| Free quota | GitHub Free personal: "15 GB-month" storage, "120 hrs" compute per month. Page says "hrs", not "core hours"; the "Included usage multiplier" for 2-core is 2, so 2-core use is probably 60 wall-clock hours (inference). | https://docs.github.com/en/billing/concepts/product-billing/github-codespaces |
| Blocked at quota, no card | "If your account does not have a valid payment method on file, usage is blocked once you use up your quota." | https://docs.github.com/en/managing-billing-for-your-products/managing-billing-for-github-codespaces/about-billing-for-github-codespaces (read via the equivalent billing page above) |
| Machines | "from 2 cores, 8 GB RAM, and 32 GB storage, up to 32 cores, 128 GB RAM, and 128 GB storage". Which sizes free accounts may pick: not stated on pages read. | https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces |
| Idle timeout | "By default this period is 30 minutes"; "The time must be between 5 minutes and 240 minutes (4 hours)." | https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces |
| Stopped codespace is deleted | "automatically deleted after they have been stopped and have remained inactive for 30 days" (default; 30 days max) | https://docs.github.com/en/codespaces/setting-your-user-preferences/configuring-automatic-deletion-of-your-codespaces |
| Stopped = app down | "If your codespace has stopped after a period of inactivity, you'll need to ensure to restart your application" | https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-port-forwarding-for-github-codespaces |
| Port visibility | `gh codespace ports visibility CODESPACE-PORT:SETTINGS`, e.g. "80:private 3000:public 3306:org"; `public` = "Visible to anyone who knows the URL and port number"; default `private`. Public ports need no authentication. | https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace |
| `portsAttributes` cannot set it | The devcontainer spec lists `label`, `protocol`, `onAutoForward`, `requireLocalPort`, `elevateIfNeeded`; no visibility key. Community workaround: run the `gh` command from `postAttachCommand`; GitHub declined public-by-default. | https://raw.githubusercontent.com/devcontainers/spec/main/docs/specs/devcontainerjson-reference.md ; https://github.com/orgs/community/discussions/4068 |
| HTTPS caveat | "If you update a port with public visibility to use HTTPS, the port's visibility will automatically change to private." | forwarding-ports page above |
| URL | "`https://CODESPACENAME-PORT.app.github.dev`" | forwarding-ports page above |
| Interstitial for visitors | Not stated in official docs. Only a third-party guide reports a "Continue" page on `app.github.dev` URLs (snippet only, unverified): https://hri2024.jibo.media.mit.edu/Setting-Up-Your-Codespace | search result, 2026-10-13 |
| Docker-in-Docker | Feature exists: `"ghcr.io/devcontainers/features/docker-in-docker:4": {}`. Codespaces-specific confirmation: not read. Not needed if the single image runs under supervisor directly. | https://raw.githubusercontent.com/devcontainers/features/main/src/docker-in-docker/README.md |

### 3. Other free tiers (suitability for ~1 GB, zero spend)

- **Render free web service**: 512 MB RAM, 0.1 CPU (https://render.com/docs/compute-plans); spins down after 15 minutes without traffic, about a minute to spin up, 750 free hours/month; free Postgres "expire 30 days after creation" with a 14-day grace period (https://render.com/docs/free). Not suitable: 512 MB is below the ~1 GB peak.
- **Fly.io**: "New organizations don't have a free tier or a monthly free usage allowance"; trial is "up to 2 hours of Machine runtime or 7 days"; card needed after the trial; smallest machine 256 MB at USD 2.19/month (https://docs.fly.io/about/pricing). Not suitable.
- **Oracle Cloud Always Free**: A1 Flex pool equals "2 OCPUs and 12 GB of memory" for Always Free tenancies, 200 GB block storage (https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm). Sign-up: "most users need a mobile phone number and a credit card ... Your credit card will not be charged unless you upgrade" (https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm). Idle reclaim rule: instance idle if over 7 days CPU p95 <20%, network <20% and memory <20% (A1), which this demo would likely match, so reclamation is a risk. Arm image needed. Technically the best fit, but needs a card.
- **Koyeb free**: "512MB of RAM, 0.1 vCPU, and 2GB of SSD", scale-to-zero after 1 hour, "should not be used for production applications" (https://www.koyeb.com/docs/reference/instances). The pricing page lists no free compute instance and does not state a card rule (https://www.koyeb.com/pricing). Not suitable (512 MB).

## Implications for REQ-IDs

No REQ-ID text was read for this note. For the owner: D-36 (zero spend) conflicts with a durable Docker Space (USD 9/month PRO). A single image on one port with a uid-1000 user, `app_port` in README YAML, and Postgres data on ephemeral disk (reset nightly matches the ephemeral model) would work on a Space if the owner pays. Any host must keep `/api` same-origin through Next rewrites; opening `*.hf.space` directly avoids the iframe cookie limits. Record the decision in DECISIONS-NEEDED.md.

## Recommendation

Zero-spend options, ranked by durability and effort:

1. **Oracle Always Free A1 VM** (durable, free, needs a card for verification, Arm build, idle-reclaim risk, owner must run a reverse proxy/TLS).
2. **Codespaces** (no card, 5 minutes of effort, not durable; a link that works only while the owner has the codespace running).
3. **HF Docker Space at USD 9/month PRO** (least effort and a stable `*.hf.space` URL, but breaks D-36 until the owner approves the spend).

Owner steps if HF PRO is approved:
1. Create a Hugging Face account and subscribe to PRO (or accept the spend decision).
2. Create a Docker Space (public); note `owner/space-name`.
3. Create a fine-grained or write access token and add it as GitHub secret `HF_TOKEN`.
4. Add Space runtime secrets in Settings (sandbox values only).
5. Add the `hub-sync` workflow (README YAML needs `sdk: docker`, `app_port: <port>`); optionally a nightly job calling `restart_space(..., factory_reboot=True)`.

Owner steps if Codespaces:
1. Open a codespace on the repo with a devcontainer that starts the image.
2. In the Ports tab (or `gh codespace ports visibility PORT:public`) set the port public.
3. Raise the idle timeout (max 4 h) and keep the tab or a client active; share the `app.github.dev` URL.

## Open questions

- Does the HF PRO requirement apply to existing free accounts' pre-existing Docker Spaces? Not stated.
- HF build time and image size limits: not stated.
- Does Codespaces show a visitor warning page on public ports, and which machine sizes does a free account get?
- Does a uid-1000 container allow Postgres `initdb` under the HF runtime (expected yes; untested)?

## Sources

- https://huggingface.co/docs/hub/spaces-overview
- https://huggingface.co/docs/hub/spaces-gpus
- https://huggingface.co/docs/hub/spaces-sdks-docker
- https://huggingface.co/docs/hub/spaces-config-reference
- https://huggingface.co/docs/hub/spaces-storage
- https://huggingface.co/docs/hub/spaces-embed
- https://huggingface.co/docs/hub/spaces-cookie-limitations
- https://huggingface.co/docs/hub/spaces-github-actions
- https://huggingface.co/docs/hub/security-tokens
- https://huggingface.co/docs/huggingface_hub/main/en/guides/manage_spaces
- https://huggingface.co/docs/huggingface_hub/main/en/package_reference/hf_api
- https://huggingface.co/pricing
- https://huggingface.co/content-policy
- https://discuss.huggingface.co/t/docker-sdk-now-marked-as-paid-when-creating-a-new-space/177580
- https://docs.github.com/en/billing/concepts/product-billing/github-codespaces
- https://docs.github.com/en/codespaces/about-codespaces/what-are-codespaces
- https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace
- https://docs.github.com/en/codespaces/setting-your-user-preferences/setting-your-timeout-period-for-github-codespaces
- https://docs.github.com/en/codespaces/setting-your-user-preferences/configuring-automatic-deletion-of-your-codespaces
- https://docs.github.com/en/codespaces/troubleshooting/troubleshooting-port-forwarding-for-github-codespaces
- https://github.com/orgs/community/discussions/4068
- https://raw.githubusercontent.com/devcontainers/spec/main/docs/specs/devcontainerjson-reference.md
- https://raw.githubusercontent.com/devcontainers/features/main/src/docker-in-docker/README.md
- https://render.com/docs/free
- https://render.com/docs/compute-plans
- https://docs.fly.io/about/pricing
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm
- https://www.koyeb.com/docs/reference/instances
- https://www.koyeb.com/pricing
