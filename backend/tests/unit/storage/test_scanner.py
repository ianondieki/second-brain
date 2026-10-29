"""Attachment scanning (REQ-PROP-01, D-36): the demo fake scanner calls the EICAR test string infected and anything
else clean, and runs only in dev and test; ClamAV is refused until it returns after the prototype (fail closed)."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from pydantic import SecretStr

from bridge.config import ConfigurationError, Settings
from bridge.storage.scanner import EICAR, FakeScanner, Verdict, scanner_from_settings


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_the_signature_is_the_standard_eicar_string() -> None:
    # The published SHA-256 of the 68-byte EICAR test file.
    assert len(EICAR) == 68
    assert hashlib.sha256(EICAR).hexdigest() == "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"


async def test_eicar_is_infected_and_anything_else_clean() -> None:
    scanner = FakeScanner()
    assert scanner.name == "fake-demo"
    infected = await scanner.scan(b"%PDF-1.7\n" + EICAR + b"\n%%EOF")
    assert infected.verdict == Verdict.INFECTED
    assert infected.signature == "Eicar-Test-Signature"
    clean = await scanner.scan(b"%PDF-1.7 an ordinary file")
    assert clean.verdict == Verdict.CLEAN
    assert clean.signature is None


@pytest.mark.parametrize("env", ["dev", "test"])
def test_the_fake_runs_in_dev_and_test(env: str) -> None:
    assert isinstance(scanner_from_settings(settings(app_env=env)), FakeScanner)


def test_the_fake_is_refused_in_staging() -> None:
    with pytest.raises(ConfigurationError, match="only in dev and test"):
        scanner_from_settings(settings(app_env="staging"))


def test_clamav_is_refused_until_after_the_prototype() -> None:
    with pytest.raises(ConfigurationError, match="D-36"):
        scanner_from_settings(settings(attachment_scanner="clamav"))
