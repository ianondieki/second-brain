# Backend image (api and worker). Python 3.12 per docs/spec/08; dependencies from uv.lock only.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
# REQ-ENG-12, REQ-FND-02: dev tools are left out of the image unless it is built for dev, test or staging with
# --build-arg WITH_DEV_TOOLS=true (infra/docker-compose.dev.yml sets it): the dev/test clock router, and the demo seed
# and helpers, which carry the demo accounts' public credentials. bridge.main mounts the clock router only where its
# module exists and APP_ENV is not production; python -m bridge.seed imports the demo seed only for --demo. A
# production image never carries either.
ARG WITH_DEV_TOOLS=false
RUN if [ "$WITH_DEV_TOOLS" != "true" ]; then rm -rf src/bridge/testclock.py src/bridge/demo src/bridge/seed/demo; fi
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config
COPY ai ./ai
COPY seed ./seed
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 bridge
USER bridge
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
# Idle connections stay open 75 s, not uvicorn's default 5 s. Next.js rewrites proxy /api through httpxy's own
# keep-alive agent, which has no idle timeout, so the API is the side that closes them; a request sent in the moment
# the API closes one is reset and Next answers a plain 500. The e2e suite's gaps between requests often lasted about
# 5 s (a flake, P16-F); a socket idle exactly 75 s is far rarer. This narrows the race, it does not remove it
# (tasks/P16-F.md: a client-side idle timeout or a retry would; check the edge proxy's idle timeout in Phase 8).
CMD ["uvicorn", "bridge.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-keep-alive", "75"]
