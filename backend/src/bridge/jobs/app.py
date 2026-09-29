"""The Procrastinate app. Worker: ``procrastinate --app=bridge.jobs.app.app worker``.

Tasks live in the modules listed in ``import_paths``; each task sets its own tenant context (one tenant per job,
docs/spec/08 Tenancy). The connector is opened by the worker or by ``open_async()`` in the API lifespan.
"""

from __future__ import annotations

from procrastinate import App, PsycopgConnector

from bridge.config import get_settings
from bridge.logging import install_job_log_redaction


def conninfo() -> str:
    """libpq connection string for the app role, from ``DATABASE_URL`` (SQLAlchemy form)."""
    url = get_settings().database_url.get_secret_value()
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


# Task modules (loaded by the worker; the API defers through bridge.jobs.outbox and never imports them).
IMPORT_PATHS = [
    "bridge.jobs.provenance",
    "bridge.jobs.audit",
    "bridge.jobs.notifications",
    "bridge.jobs.reminders",
    "bridge.jobs.research",
]

app = App(connector=PsycopgConnector(conninfo=conninfo()), import_paths=IMPORT_PATHS)
# The worker imports this module before the CLI configures logging: its job records are redacted from the start.
install_job_log_redaction()
