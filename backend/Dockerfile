# Backend image (api and worker). Python 3.12 per docs/spec/08; dependencies from uv.lock only.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config
COPY seed ./seed
RUN uv sync --frozen --no-dev && useradd --system --uid 10001 bridge
USER bridge
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "bridge.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
