# Public demo

## Purpose

Give anyone a link to a working Bridge demo: the whole seeded product in one container (`infra/demo/space/`), in
public-demo mode (persona sign-in, locked account and upload routes, a fictional-data banner, `noindex`, a reset every
night at 03:00 EAT). Three ways to host it, in the order the owner can use them:

- **A. GitHub Codespaces**: now, zero spend, no card. The address stays private until you publish it with one
  command, and works only while the codespace runs.
- **B. Hugging Face Docker Space**: after D-71 (a), a paid Hugging Face plan (PRO, USD 9 a month). A stable
  `*.hf.space` address that wakes on visit.
- **C. Oracle Cloud Always Free Arm VM**: after D-71 (b), a card for Oracle's sign-up verification (not charged on
  the free tier). Durable, your own `sslip.io` address with HTTPS.

Nothing is published by itself: before any of them goes public (a public codespace port, a Space, the VM's
address), work through **D. The go-live checklist**.

Requirement: REQ-FND-04 (P28 track PD). Research: `docs/platform/research/public-demo-hosting.md`.

## What the image is

`infra/demo/space/Dockerfile` builds one image with PostgreSQL 16 + pgvector, SeaweedFS (S3), Mailpit, the API, the
job worker and the web app; `run.py` supervises them as uid 1000 and serves only the web app, on port 7860. Each boot
makes new throwaway secrets, starts from empty data, migrates and loads the demo seed. Email stays in an internal
Mailpit, SMS and payments are simulated, LLM calls answer with the deterministic fallback, and SeaweedFS's usage
statistics are off. **One connection leaves the container**: when a proposal is registered, the worker asks a public
timestamp service for an RFC 3161 timestamp of its certificate (DigiCert, with FreeTSA as the fallback; the same as
`make demo`), sending a hash, never the text. Nothing else is sent anywhere. It boots in about a minute and uses about
600 MB of memory (`infra/demo/space/README.md` has the measured figures; give it at least 1 GB). It is a demo only:
never point it at real data or real providers.

**The nightly reset** (03:00 EAT, `RESET_HOUR_EAT` in `infra/demo/space/run.py`; `infra/demo/space/README.md` has its
timing): the banner's "03:00 EAT" is written into the web's copy (`publicDemo.banner` in `frontend/locales/en.json`
and `sw.json`), not read from the image, so a change to the reset hour changes those two strings and the API's
`RESET_HOUR_EAT` in `backend/src/bridge/demo/public_access.py` (what `/api/public/demo` reports) in the same commit.

`.github/workflows/demo-image.yml` builds it on every push to the integration branch that touches `backend/`,
`frontend/` or `infra/`, and pushes `ghcr.io/ianondieki/bridge-demo:latest` and `:<commit SHA>`; run it by hand with
**arm64** ticked to also build the Arm image (tag `:multiarch`).

## A. GitHub Codespaces (now, zero spend)

1. Open https://github.com/ianondieki/second-brain, switch the branch selector to `claude/eloquent-hypatia-aa3577`.
2. **Code** > **Codespaces** > **...** > **New with options**: branch `claude/eloquent-hypatia-aa3577`, dev container
   configuration "Bridge public demo", machine type 2-core (8 GB). **Create codespace**.
3. Wait. The first time, the codespace builds the image from the checkout (about 10-15 minutes); then the demo boots
   (about a minute, a little more on 2 cores). `tail -f ~/demo.log` shows the boot; it is ready when the log says
   `ready in N s`. The terminal prints the address, `https://<codespace-name>-7860.app.github.dev`, and the port is
   **private**: the address opens only for you, signed in to GitHub. Try the demo there first.
4. Work through **D. The go-live checklist**. Only then publish the port, in the codespace's terminal:
   ```bash
   bash .devcontainer/public-url.sh --publish
   ```
   and share the address it prints. Visitors need no GitHub account.
   - If it says it could not change the visibility: open the **Ports** tab, right-click port 7860 (label "Demo"),
     **Port Visibility** > **Public**. Opening a public port as HTTPS turns it private again: leave the protocol as
     HTTP.
   - To take the link down without stopping the codespace: `bash .devcontainer/public-url.sh --private`.
5. Keep it up while you need it: GitHub stops an idle codespace after 30 minutes by default. Raise it to the maximum,
   240 minutes: https://github.com/settings/codespaces > **Default idle timeout**. A stopped codespace serves
   nothing; reopen it (Code > Codespaces > the codespace) and the demo boots again, from fresh data.
6. Stop it: Code > Codespaces > **...** > **Stop codespace** (or let it idle out). Delete it when done to free the
   free quota's storage (15 GB-month). The free compute quota is 120 hours a month, which a 2-core machine uses at
   double rate: about 60 hours of a running demo.

Faster starts: once the GHCR package is public (D below), edit `.devcontainer/devcontainer.json` as its comment says
(`"image": "ghcr.io/ianondieki/bridge-demo:latest"` instead of `"build"`): the codespace then pulls the image instead
of building it.

## B. Hugging Face Docker Space (after D-71 (a))

1. Hugging Face account with the PRO plan (Docker Spaces need a paid plan since July 2026).
2. https://huggingface.co/new-space: owner you, a name (for example `bridge-demo`), **SDK: Docker**, blank template,
   hardware **CPU basic** (free with PRO), **Public**. Note `owner/space-name`.
3. https://huggingface.co/settings/tokens > **Create new token**: fine-grained, write access to that Space only
   (or the `write` role). Copy it.
4. In GitHub: **Settings** > **Secrets and variables** > **Actions**:
   - **Secrets** > New repository secret `HF_TOKEN` = the token.
   - **Variables** > New repository variable `HF_SPACE` = `owner/space-name`.
5. Make the GHCR package public (D below): the Space pulls `ghcr.io/ianondieki/bridge-demo:latest` anonymously.
6. **Actions** > **demo-space** > **Run workflow**. It writes a two-file Space (a `Dockerfile` that is just
   `FROM ghcr.io/ianondieki/bridge-demo:latest` and a `README.md` with `sdk: docker`, `app_port: 7860`) and uploads
   it. Without the secret or the variable it only writes a notice.
7. The Space builds and boots (a few minutes). Share `https://<owner>-<space-name>.hf.space` (the direct address: on
   `huggingface.co/spaces/...` the app sits in a frame, where browsers limit its cookies). The app derives its own
   address from `SPACE_HOST`, which Hugging Face sets.
8. Updates: after demo-image.yml pushes a new `:latest`, Space settings > **Factory rebuild** (or run demo-space
   again). A Space sleeps after 48 hours without visitors and wakes on the next visit (from fresh data).
9. Stop it: Space settings > **Pause** (or delete the Space); remove `HF_TOKEN` when no longer needed.

## C. Oracle Cloud Always Free Arm VM (after D-71 (b))

1. Oracle Cloud account (Always Free; a card verifies the sign-up). Create an instance: shape **VM.Standard.A1.Flex**
   (Ampere, Always Free eligible) with 1 OCPU and 6 GB, image **Ubuntu 24.04** (aarch64), your SSH key.
2. Build the Arm image: **Actions** > **demo-image** > **Run workflow** with **arm64** ticked (QEMU: expect well over
   30 minutes). It pushes `ghcr.io/ianondieki/bridge-demo:multiarch`. Make the package public (D below).
3. Open ports 80 and 443 in two places:
   - Oracle: the instance's subnet > **Security List** > **Add Ingress Rules**: source `0.0.0.0/0`, TCP, destination
     ports `80` and `443`.
   - The VM's own firewall (Oracle's Ubuntu images ship iptables rules that drop them):
     ```bash
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
     sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
     sudo netfilter-persistent save
     ```
4. Your address: the VM's public IP with dashes plus `.sslip.io`, which resolves to that IP with no DNS set-up. For
   IP `129.151.10.20` it is `129-151-10-20.sslip.io`.
5. Install Docker and Caddy, and run the demo bound to localhost only (Caddy is the only thing on 80/443):
   ```bash
   sudo apt-get update && sudo apt-get install -y docker.io caddy
   sudo docker run -d --name bridge-demo --restart unless-stopped \
     -p 127.0.0.1:7860:7860 \
     -e PUBLIC_BASE_URL=https://129-151-10-20.sslip.io \
     ghcr.io/ianondieki/bridge-demo:multiarch
   ```
6. `/etc/caddy/Caddyfile` (replace the address with yours), then `sudo systemctl reload caddy`. Caddy gets a Let's
   Encrypt certificate for the name on its own, redirects HTTP to HTTPS, and replaces any `X-Forwarded-For` a visitor
   sends with the visitor's real address (the API's per-visitor throttles rely on it):
   ```
   129-151-10-20.sslip.io {
   	encode zstd gzip
   	reverse_proxy 127.0.0.1:7860
   }
   ```
7. Check: `sudo docker logs -f bridge-demo` until `ready in N s`, then open `https://129-151-10-20.sslip.io`.
8. Updates: run demo-image with arm64 again, then
   `sudo docker pull ghcr.io/ianondieki/bridge-demo:multiarch && sudo docker rm -f bridge-demo` and the `docker run`
   above. Oracle may reclaim an Always Free instance that stays idle for 7 days (CPU, network and memory all low).
9. Stop it: `sudo docker rm -f bridge-demo` and `sudo systemctl stop caddy` (or terminate the instance).

## D. Go-live checklist (before sharing any link)

- [ ] **D-71** decided: which host (A now; B or C need the spend or the card).
- [ ] **D-38** (news excerpts): the image runs `PUBLIC_DEMO_CONTENT=fictional`, so the 13 news excerpts stay out and
      only the 6 official-source excerpts load. Set `PUBLIC_DEMO_CONTENT=full` (for example `-e
      PUBLIC_DEMO_CONTENT=full` on `docker run`) only after D-38 is decided and the publishers' terms are reviewed.
- [ ] **G6** (directory): with `fictional`, the provisional directory of real Kenyan organisations
      (`backend/seed/ke_provisional.yaml`) is left out; `full` loads it, so `full` also waits for G6's official
      citations for every real organisation it names.
- [ ] **D-39** (legal drafts): the NDA templates, attestations and notices stay labelled as drafts ("DRAFT — NOT
      LEGAL ADVICE") until the legal review; do not remove the labels for the demo.
- [ ] **The GHCR package is public**, or no host but this repository's Actions can pull it: GitHub > your profile >
      **Packages** > **bridge-demo** > **Package settings** > **Danger Zone** > **Change visibility** > **Public**.
      The image holds no secret (they are generated at each boot) and its source is this repository.
- [ ] **The one outbound connection is acceptable**: when a proposal is registered, the worker asks a public timestamp
      service for an RFC 3161 timestamp of its certificate: DigiCert (`timestamp.digicert.com`, plain HTTP), with
      FreeTSA (`freetsa.org`) as the fallback, as `make demo` does. They receive a hash and the host's address, never
      the proposal. The provenance demo depends on them and the image has no switch for them; nothing else leaves the
      container (email, SMS and payments are simulated, LLM calls use the fallback, SeaweedFS's statistics are off).
- [ ] Open the link in a private window: the persona picker shows, the banner says the data is fictional and resets
      nightly, and `/robots.txt` disallows everything.
- [ ] **Each visitor gets their own throttle**, checked on the chosen host right after it is reachable and before the
      link is shared. Sign-in throttles (30 persona sign-ins a minute) are counted per visitor address, and the API
      only knows that address from the `X-Forwarded-For` header the host's edge proxy sends. From two different
      networks (a laptop on Wi-Fi and a phone on mobile data), open the link and sign in, then read the API's access
      log: Codespaces `grep '\[api\]' ~/demo.log | tail -20`; Docker `docker logs <container> 2>&1 | grep '\[api\]'
      | tail -20`. Each line starts with the address the API resolved: `INFO: 41.90.64.10:0 - "POST /api/auth/..."`
      (`:0` means it came from the header). The two visitors must show two different public addresses. If every line
      shows `127.0.0.1:<port>` (no header) or one shared address, all visitors share one throttle and one busy visitor
      can lock the others out: do not share the link; report it. Caddy (part C) replaces any `X-Forwarded-For` a
      visitor sends with the address it sees, so it passes this check by design; Hugging Face's and Codespaces' edge
      proxies were not verified (if one appends to a visitor's own header, the API takes the right-most address,
      which is the edge's view of the visitor). A bare `docker run -p` with no proxy in front sends no header at all.

**Stopping it** (any host): A, stop the codespace; B, pause the Space; C, `sudo docker rm -f bridge-demo`. To withdraw
the image too, make the package private again or delete it (Package settings).

## Troubleshooting

- **The page does not load yet**: the boot takes about a minute (migrations and the seed), and so does the nightly
  reset. Codespaces: `tail -f ~/demo.log`; Docker: `docker logs -f <container>`. Look for `ready in N s`, or for
  `boot failed`.
- **Force a reset now**: `python3 /opt/infra/demo/space/run.py reset` inside the container (Codespaces terminal, or
  `docker exec <container> python3 /opt/infra/demo/space/run.py reset`), or `docker kill -s USR1 <container>`.
- **Out of memory**: give the container at least 1 GB, 2 GB for traffic (the measured figures are in the image's
  README).
- **"exec format error" on the Oracle VM**: the image is amd64 only; pull `:multiarch` after an arm64 run.
