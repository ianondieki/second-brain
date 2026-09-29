"""The local demo's compose override and its launcher (P9 ``make demo``; REQ-FND-02; PLAN.md §8, D-36).

``infra/docker-compose.demo.yml`` runs the dev stack as its own project with APP_ENV=dev, both feature flags, the fake
scanner and embedder, no ClamAV, generated secrets that win over ``backend/.env``, the demo seed in the migrate step,
and memory limits that fit Docker Desktop's 4 GB. ``infra/demo/demo.py`` writes the throwaway secrets once (valid for
the app's fail-closed settings, never overwritten, gitignored) and wipes volumes only when ``reset`` is confirmed.
``docker compose config`` validates the merged file.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml
from pydantic import SecretStr

from bridge.config import Settings

REPO = Path(__file__).resolve().parents[4]
DEV = REPO / "infra" / "docker-compose.dev.yml"
DEMO = REPO / "infra" / "docker-compose.demo.yml"
LAUNCHER = REPO / "infra" / "demo" / "demo.py"
STACK = ("postgres", "mailpit", "s3", "migrate", "api", "worker", "web")
BUDGET_MIB = 3 * 1024  # the whole stack's limits; Docker Desktop has 4 GB on the owner's laptop
UNITS = {"k": 1 / 1024, "m": 1, "g": 1024}


class ComposeLoader(yaml.SafeLoader):
    """YAML with Compose's merge tags (``!override``, ``!reset``) read as plain values."""


def _plain(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


for _tag in ("!override", "!reset"):
    ComposeLoader.add_constructor(_tag, _plain)


def load(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.load(path.read_text(encoding="utf-8"), Loader=ComposeLoader)  # noqa: S506
    return document


def launcher() -> ModuleType:
    spec = importlib.util.spec_from_file_location("demo_launcher", LAUNCHER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mib(value: str) -> float:
    number, unit = re.fullmatch(r"(\d+)([kmg])", value.lower()).groups()  # type: ignore[union-attr]
    return int(number) * UNITS[unit]


def test_the_demo_is_its_own_project_so_a_reset_never_touches_the_dev_stack() -> None:
    assert load(DEMO)["name"] == "bridge-demo"
    assert load(DEV)["name"] == "bridge"


def test_the_demo_runs_as_dev_with_the_flags_the_fake_scanner_and_no_clamav() -> None:
    services = load(DEMO)["services"]
    for name in ("migrate", "api", "worker"):
        env = services[name]["environment"]
        assert env["APP_ENV"] == "dev"
        assert (env["FEATURE_TIER2_ENABLED"], env["FEATURE_DEALS_ENABLED"]) == ("true", "true")
        assert (env["ATTACHMENT_SCANNER"], env["EMBEDDER"], env["SMS_PROVIDER"]) == ("fake", "fake", "fake")
    assert "clamav" not in services
    assert load(DEV)["services"]["clamav"]["profiles"] == ["full"]  # only `make dev-full` starts it


def test_the_generated_secrets_win_over_backend_env_and_the_api_still_gets_no_signing_key() -> None:
    services = load(DEMO)["services"]
    for name in ("migrate", "api", "worker"):
        assert services[name]["env_file"] == [
            {"path": "../backend/.env", "required": False},
            {"path": "demo/backend.env", "required": True},
        ]
        assert "PROVENANCE_SIGNING_KEY" not in services[name]["environment"]  # the dev file's api override stays
    assert load(DEV)["services"]["api"]["environment"]["PROVENANCE_SIGNING_KEY"] == ""


def test_the_migrate_step_seeds_the_demo_after_the_buckets_and_the_signing_key() -> None:
    script = " ".join(load(DEMO)["services"]["migrate"]["command"])
    order = ["alembic upgrade head", "ensure-buckets", "register-key --if-configured", "python -m bridge.seed --demo"]
    positions = [script.index(step) for step in order]
    assert positions == sorted(positions)


def test_every_service_has_a_memory_limit_and_the_stack_fits_in_three_gigabytes() -> None:
    services = load(DEMO)["services"]
    limits = {name: mib(services[name]["mem_limit"]) for name in STACK}
    assert sum(limits.values()) <= BUDGET_MIB, limits


def test_the_launcher_writes_valid_secrets_once_and_never_overwrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = launcher()
    example = tmp_path / "backend" / ".env.example"
    example.parent.mkdir()
    example.write_text("APP_ENV=dev\nLLM_GLOBAL_DAILY_CAP_USD=1.00\n", encoding="utf-8")
    monkeypatch.setattr(demo, "REPO", tmp_path)
    monkeypatch.setattr(demo, "COMPOSE_ENV", tmp_path / "infra" / "demo" / ".env")
    monkeypatch.setattr(demo, "BACKEND_ENV", tmp_path / "infra" / "demo" / "backend.env")
    monkeypatch.setattr(demo, "BACKEND_DOTENV", tmp_path / "backend" / ".env")
    monkeypatch.setattr(demo, "BACKEND_EXAMPLE", example)
    created = demo.init()
    assert created == [str(Path("infra/demo/.env")), str(Path("infra/demo/backend.env")), str(Path("backend/.env"))]
    first = {path: path.read_bytes() for path in (demo.COMPOSE_ENV, demo.BACKEND_ENV, demo.BACKEND_DOTENV)}
    assert demo.init() == []
    assert {path: path.read_bytes() for path in first} == first  # never overwritten
    values = dict(
        line.split("=", 1) for line in demo.BACKEND_ENV.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    for name in ("DATA_ENCRYPTION_KEY", "TIER2_LOCAL_KEK", "PROVENANCE_SIGNING_KEY"):
        assert len(base64.b64decode(values[name], validate=True)) == 32, name
    settings = Settings(  # the app's own fail-closed validation accepts them
        app_env="dev",
        database_url=SecretStr("postgresql+psycopg://bridge_app:x@postgres:5432/bridge"),
        secret_key=SecretStr(values["SECRET_KEY"]),
        data_encryption_key=SecretStr(values["DATA_ENCRYPTION_KEY"]),
        recovery_code_pepper=SecretStr(values["RECOVERY_CODE_PEPPER"]),
        tier2_local_kek=SecretStr(values["TIER2_LOCAL_KEK"]),
        provenance_signing_key=SecretStr(values["PROVENANCE_SIGNING_KEY"]),
    )
    assert settings.tier2_local_kek is not None
    compose = dict(
        line.split("=", 1) for line in demo.COMPOSE_ENV.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    assert set(compose) == {"POSTGRES_SUPERUSER_PASSWORD", "BRIDGE_OWNER_PASSWORD", "BRIDGE_APP_PASSWORD"}
    assert len(set(compose.values())) == 3


def test_the_generated_files_are_gitignored() -> None:
    for path in ("infra/demo/.env", "infra/demo/backend.env", "backend/.env"):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO, check=False)  # noqa: S607
        assert result.returncode == 0, f"{path} must be gitignored"


def test_reset_wipes_nothing_unless_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = launcher()

    def must_not_run(*_: object, **__: object) -> None:
        raise AssertionError("nothing may run without --yes")

    monkeypatch.setattr(demo, "run", must_not_run)
    monkeypatch.setattr(demo, "volume_exists", lambda _name: False)
    assert demo.main(["reset"]) == 2


def test_extra_compose_files_come_from_the_environment_only(monkeypatch: pytest.MonkeyPatch) -> None:
    demo = launcher()
    monkeypatch.delenv("DEMO_COMPOSE_EXTRA", raising=False)
    assert demo.compose_files() == [str(DEV), str(DEMO)]
    monkeypatch.setenv("DEMO_COMPOSE_EXTRA", "/tmp/ca.json")  # noqa: S108 - a path string, never opened
    command = demo.compose("config")
    assert command[:4] == ["docker", "compose", "--env-file", str(demo.COMPOSE_ENV)]
    assert command[-3:] == ["-f", "/tmp/ca.json", "config"]  # noqa: S108


def test_docker_compose_validates_the_merged_demo_file(tmp_path: Path) -> None:
    """``docker compose config`` on a copy of infra/ with placeholder secret files (the real ones are generated)."""
    docker = shutil.which("docker")
    assert docker, "docker is needed for the platform (make dev, make demo); install Docker Desktop"
    infra = tmp_path / "infra"
    (infra / "demo").mkdir(parents=True)
    shutil.copy(DEV, infra / DEV.name)
    shutil.copy(DEMO, infra / DEMO.name)
    (infra / "demo" / ".env").write_text(
        "POSTGRES_SUPERUSER_PASSWORD=a\nBRIDGE_OWNER_PASSWORD=b\nBRIDGE_APP_PASSWORD=c\n"
    )
    (infra / "demo" / "backend.env").write_text("SECRET_KEY=placeholder\n")
    result = subprocess.run(
        [docker, "compose", "--env-file", str(infra / "demo" / ".env"), "-f", str(infra / DEV.name), "-f",
         str(infra / DEMO.name), "config", "--format", "json"],
        cwd=tmp_path, capture_output=True, text=True, check=False, timeout=60,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    merged = json.loads(result.stdout)
    assert merged["name"] == "bridge-demo"
    assert set(STACK) <= set(merged["services"])
    assert "clamav" not in merged["services"]
    assert merged["services"]["api"]["environment"]["APP_ENV"] == "dev"
    assert merged["services"]["api"]["environment"]["PROVENANCE_SIGNING_KEY"] == ""
    assert merged["services"]["api"]["build"]["args"]["WITH_TEST_CLOCK"] == "true"
