"""The demo seed and helpers stay out of a production image (P9; REQ-FND-02; THREAT_MODEL §2, "known-credential
demo accounts reach a hosted deployment").

The backend image deletes ``bridge/demo`` and ``bridge/seed/demo`` unless built with ``WITH_DEV_TOOLS=true`` (only
the dev compose stack sets it); ``python -m bridge.seed`` imports the demo seed only for ``--demo``, so the reference
seed runs in an image without it, and ``--demo`` there answers that the demo is not in the image.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest
from pydantic import SecretStr

from bridge.config import BACKEND_DIR, get_settings
from bridge.seed import __main__ as seed_command
from bridge.seed.reference import SEED_TABLES
from tests.integration.test_testclock_excluded import image_removals

DEMO_PACKAGES = ("src/bridge/demo", "src/bridge/seed/demo")


def test_the_image_deletes_both_demo_packages_unless_built_with_dev_tools() -> None:
    removals = image_removals()
    for package in DEMO_PACKAGES:
        assert (BACKEND_DIR / package / "__init__.py").is_file(), package  # the path it deletes is the package
        assert package in removals, package


def test_nothing_outside_the_demo_packages_imports_them_at_start() -> None:
    """Importing the app, the worker's task modules and the seed command loads neither demo package."""
    code = (
        "import sys; import bridge.main, bridge.seed.__main__, bridge.jobs.provenance, bridge.jobs.reminders;"
        " print(sorted(m for m in sys.modules if m.startswith(('bridge.demo', 'bridge.seed.demo'))))"
    )
    env = {"PYTHONPATH": str(BACKEND_DIR / "src"), "APP_ENV": "test", "DATABASE_URL": "postgresql+psycopg://x@h/d"}
    env |= {
        "SECRET_KEY": "k" * 40,
        "DATA_ENCRYPTION_KEY": "dGVzdC1kYXRhLWtleS0wMTIzNDU2Nzg5YWJjZGVmMDE=",
        "RECOVERY_CODE_PEPPER": "p" * 40,
        "PATH": "/usr/bin:/bin",
    }
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_the_seed_command_runs_without_the_demo_and_refuses_demo_there(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = get_settings().model_copy(update={"database_owner_url": SecretStr("postgresql+psycopg://o@h/d")})
    real = importlib.util.find_spec

    def without_demo(name: str, package: str | None = None) -> object:
        return None if name == seed_command.DEMO_PACKAGE else real(name, package)

    async def reference_only(url: str, given: object) -> tuple[dict[str, int], None]:
        return dict.fromkeys(SEED_TABLES, 1), None

    monkeypatch.setattr("importlib.util.find_spec", without_demo)
    monkeypatch.setattr(seed_command, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_command, "run", reference_only)
    assert seed_command.main([]) == 0
    assert seed_command.main(["--demo"]) == 2
    assert "the demo seed is not in this image" in capsys.readouterr().err
