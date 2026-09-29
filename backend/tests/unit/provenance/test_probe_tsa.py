"""REQ-PROV-01 / REQ-AUD-01: ``python -m bridge.provenance probe-tsa`` checks each configured TSA on its own with the
worker's own client (pinned bundles, nonce and imprint, the anchors' one-minute bound), so ops prove the settings
before a release with the verifier the worker uses. Never pointed at a real TSA here: the transport is the local
openssl TSA."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from bridge.config import Settings
from bridge.provenance import __main__ as cli
from tests.openssl_tsa import LocalTsa


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "app_env": "staging",
        "tsa_url": "http://primary.test/tsr",
        "tsa_fallback_url": "http://fallback.test/tsr",
        "tsa_ca_bundle": None,
        "tsa_fallback_ca_bundle": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def run(
    monkeypatch: pytest.MonkeyPatch,
    configured: Settings,
    local_tsa: LocalTsa,
    clock: Callable[[], datetime] | None = None,
) -> int:
    monkeypatch.setattr(cli, "get_settings", lambda: configured)
    return cli.main(["probe-tsa"], transport=local_tsa.transport(), clock=clock)


def test_the_probe_passes_when_every_tsa_answers_for_its_pinned_bundle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local_tsa: LocalTsa
) -> None:
    configured = settings(tsa_ca_bundle=local_tsa.ca_pem, tsa_fallback_ca_bundle=local_tsa.ca_pem)
    assert run(monkeypatch, configured, local_tsa) == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split(": ", 1)[0] for line in out] == ["ok http://primary.test/tsr", "ok http://fallback.test/tsr"]
    assert all(f"pinned to {local_tsa.ca_pem}" in line and "serial 0x" in line for line in out)


def test_the_probe_checks_each_tsa_on_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local_tsa: LocalTsa, tmp_path: Path
) -> None:
    """A fallback whose bundle does not match the TSA answering at its URL fails the probe, even though the worker
    would never reach it while the primary answers."""
    stranger = LocalTsa.create(tmp_path / "stranger")
    configured = settings(tsa_ca_bundle=local_tsa.ca_pem, tsa_fallback_ca_bundle=stranger.ca_pem)
    assert run(monkeypatch, configured, local_tsa) == 1
    captured = capsys.readouterr()
    assert captured.out.startswith("ok http://primary.test/tsr")
    assert "FAILED http://fallback.test/tsr" in captured.err
    assert "does not chain to the CA bundle pinned for this TSA" in captured.err


def test_the_probe_holds_the_anchor_bound_on_the_worker_clock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local_tsa: LocalTsa
) -> None:
    """The probe allows the anchors' one minute ahead, so a worker clock that lags the TSA fails it."""
    configured = settings(tsa_ca_bundle=local_tsa.ca_pem, tsa_fallback_url=None)
    lagging = lambda: datetime.now(UTC) - timedelta(minutes=5)  # noqa: E731
    assert run(monkeypatch, configured, local_tsa, clock=lagging) == 1
    assert "more than 60 s ahead of the local clock" in capsys.readouterr().err


def test_the_probe_fails_closed_without_a_bundle_outside_dev_and_test(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local_tsa: LocalTsa
) -> None:
    assert run(monkeypatch, settings(tsa_ca_bundle=local_tsa.ca_pem), local_tsa) == 2
    assert "TSA_FALLBACK_CA_BUNDLE" in capsys.readouterr().err


def test_an_unpinned_tsa_in_test_is_reported_as_unchecked(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], local_tsa: LocalTsa
) -> None:
    assert run(monkeypatch, settings(app_env="test", tsa_fallback_url=None), local_tsa) == 0
    assert "chain NOT checked" in capsys.readouterr().out
