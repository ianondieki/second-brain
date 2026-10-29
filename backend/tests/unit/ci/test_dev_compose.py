"""The dev compose stack (infra/docker-compose.dev.yml) keeps worker-only secrets out of the API (REQ-PROV-01,
REQ-AUD-01): the signing key and the audit_reader login reach the worker and the migrate step only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[4]
COMPOSE = REPO / "infra" / "docker-compose.dev.yml"
WORKER_ONLY = ("PROVENANCE_SIGNING_KEY", "AUDIT_READER_DATABASE_URL")


def services() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))  # resolves the << merge keys
    result: dict[str, Any] = document["services"]
    return result


def test_the_api_gets_no_signing_key_and_no_audit_reader_login() -> None:
    api = services()["api"]
    for name in WORKER_ONLY:
        assert api["environment"][name] == "", f"api must override {name} to empty (empty means unset)"
    # The override must not drop the shared environment (a YAML merge replaces the whole map otherwise).
    assert api["environment"]["DATABASE_URL"].startswith("postgresql+psycopg://bridge_app:")
    assert api["env_file"] == "../backend/.env"


def test_the_worker_and_migrate_keep_them_from_backend_env() -> None:
    for name in ("worker", "migrate"):
        service = services()[name]
        assert service["env_file"] == "../backend/.env"
        assert not set(WORKER_ONLY) & set(service["environment"]), f"{name} must take them from backend/.env"


def test_the_buckets_are_created_by_the_migrate_step_before_api_and_worker_start() -> None:
    """Never at first use: migrate runs ``python -m bridge.storage ensure-buckets`` once s3 is up, and api and worker
    wait for migrate to finish."""
    stack = services()
    migrate = stack["migrate"]
    script = " ".join(migrate["command"])
    assert "python -m bridge.storage ensure-buckets" in script
    assert script.index("alembic upgrade head") < script.index("ensure-buckets")
    assert "s3" in migrate["depends_on"]
    assert migrate["depends_on"]["postgres"] == {"condition": "service_healthy"}
    for name in ("api", "worker"):
        assert stack[name]["depends_on"]["migrate"] == {"condition": "service_completed_successfully"}
