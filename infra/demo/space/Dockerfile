# The public demo image (P28 track PD; REQ-FND-04): the whole seeded product in ONE container on ONE port (7860), for
# any Docker host: GitHub Codespaces, a Hugging Face Docker Space, an Oracle Always Free Arm VM. Demo only: fictional
# data, fake providers, throwaway secrets generated at every boot by run.py; never production (README.md here).
#
#   docker build -f infra/demo/space/Dockerfile -t bridge-demo .      (the context is the repository root)
#   docker run --rm -p 7860:7860 bridge-demo
#
# Stages: (a) the backend's venv and source, as backend/Dockerfile with WITH_DEV_TOOLS=true (the demo seed, the demo
# helpers and the dev/test clock stay in: this is a demo image); (b) the Next.js standalone build with its /api
# rewrites baked to the API on 127.0.0.1:8000; (c) the runtime: PostgreSQL 16 + pgvector from the PGDG apt repository,
# the SeaweedFS (S3) and Mailpit binaries and Node 22's binary copied from their pinned images, and run.py, the
# standard-library supervisor that runs it all as uid 1000 (Hugging Face runs Docker Spaces as uid 1000).
# Every stage is Debian bookworm (glibc), so the venv's wheels and the web's native modules (sharp) match the runtime.
# Builds for linux/amd64 and linux/arm64: nothing below names an architecture (apt and the multi-arch images pick it).
#
# Base images are pinned by tag; their multi-arch index digests, read on 2026-10-13:
#   python:3.12-slim-bookworm      sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
#   node:22-bookworm-slim          sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392
#   ghcr.io/astral-sh/uv:0.12.18   sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc
#   chrislusf/seaweedfs:4.47       sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882
#   axllent/mailpit:v1.31.2        sha256:74d609a42ec279aa63c6b4622a6fa9b5408d1ad5b1d76a1c4be40a265ce0863d

# ---- (a) backend: dependencies from uv.lock only (backend/Dockerfile's steps and pins) ------------------------------
FROM python:3.12-slim-bookworm AS backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# WITH_DEV_TOOLS=true behaviour: src/bridge/testclock.py, src/bridge/demo and src/bridge/seed/demo are kept.
COPY backend/src ./src
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/config ./config
COPY backend/ai ./ai
COPY backend/seed ./seed
RUN uv sync --frozen --no-dev

# ---- (b) web: frontend/Dockerfile's steps on Debian, the API on loopback ---------------------------------------------
FROM node:22-bookworm-slim AS web-deps
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-bookworm-slim AS web
WORKDIR /web
# Rewrites are resolved at build time (frontend/next.config.ts): /api goes to the API inside this container. No
# NEXT_PUBLIC_SITE_ORIGIN: the certificate's QR then carries the path alone, which works on every host.
ENV NEXT_TELEMETRY_DISABLED=1 API_ORIGIN=http://127.0.0.1:8000 NEXT_PUBLIC_SITE_ORIGIN=
COPY --from=web-deps /web/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

# ---- (c) runtime -----------------------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
# PostgreSQL 16 and pgvector from the PGDG repository. Its signing key (fingerprint
# B97B 0AFC AA1A 47F0 44F2 44A0 7FCC 7D46 ACCC 4CF8) is checked against the SHA-256 below before apt trusts it; when
# PGDG republishes the key, compare the new fingerprint with https://wiki.postgresql.org/wiki/Apt and update the hash.
# No default cluster at install (run.py runs initdb at each boot); en_US.UTF-8 as in the dev stack's postgres image;
# tini as PID 1 (forwards signals to run.py and reaps orphans); curl for the key and for debugging.
ARG PGDG_ASC_SHA256=0144068502a1eddd2a0280ede10ef607d1ec592ce819940991203941564e8e76
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl locales tini; \
    localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc; \
    echo "${PGDG_ASC_SHA256}  /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc" | sha256sum -c -; \
    . /etc/os-release; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc]" \
      "https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update --error-on=any; \
    apt-get install -y --no-install-recommends postgresql-common; \
    sed -ri 's/#(create_main_cluster) .*$/\1 = false/' /etc/postgresql-common/createcluster.conf; \
    apt-get install -y --no-install-recommends postgresql-16 postgresql-16-pgvector; \
    rm -rf /var/lib/apt/lists/*

COPY --from=chrislusf/seaweedfs:4.47 /usr/bin/weed /usr/local/bin/weed
COPY --from=axllent/mailpit:v1.31.2 /mailpit /usr/local/bin/mailpit
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node

RUN useradd --uid 1000 --user-group --create-home --home-dir /home/demo --shell /bin/bash demo

# The backend stays root-owned (read-only to the app, as in backend/Dockerfile); the web owns its .next/cache.
COPY --from=backend /app /app
COPY --from=web --chown=1000:1000 /web/.next/standalone /web
COPY --from=web --chown=1000:1000 /web/.next/static /web/.next/static
COPY --from=web --chown=1000:1000 /web/public /web/public
# The repository's layout under /opt/infra: run.py finds the SQL in ../../postgres and the secret generators in
# ../demo.py, in the image and in a checkout alike.
COPY infra/postgres/roles.sql infra/postgres/prepare_db.sql /opt/infra/postgres/
COPY infra/demo/demo.py /opt/infra/demo/demo.py
COPY infra/demo/space/run.py /opt/infra/demo/space/run.py

ENV HOME=/home/demo LANG=en_US.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860
USER 1000:1000
WORKDIR /home/demo
EXPOSE 7860
# Healthy once the web app answers (a boot takes about a minute; so does the nightly reset, which may show unhealthy).
HEALTHCHECK --interval=30s --timeout=5s --start-period=5m --retries=3 \
  CMD ["python3", "-c", "import os, urllib.request as u; u.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/\", timeout=4)"]
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "/opt/infra/demo/space/run.py"]
