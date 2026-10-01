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
# Keep idle connections longer than the proxies in front do (Node's agent behind Next.js rewrites closes them after
# 5 s, uvicorn's default): otherwise a request sent on a connection the API is just closing is reset and Next answers a
# plain 500 (an e2e flake, P16-F). The proxy now always closes first.
CMD ["uvicorn", "bridge.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-keep-alive", "75"]
