"""REQ-PROV-01 / AC-IP-1 (timestamp half): the RFC 3161 client gets a token from a local openssl test TSA through the
production code path, and ``openssl ts -verify`` accepts the stored ``.tsr`` for the manifest's hash."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from bridge.provenance.tsa import TsaClient
from tests.openssl_tsa import LocalTsa

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "provenance"
TSA_URL = "http://tsa.test/tsr"


async def test_the_stored_tsr_verifies_with_openssl(local_tsa: LocalTsa, tmp_path: Path) -> None:
    manifest = (FIXTURES / "manifest_v1_basic.canonical.json").read_bytes()
    content_hash = hashlib.sha256(manifest).digest()
    token = await TsaClient([TSA_URL], transport=local_tsa.transport()).timestamp(content_hash)

    stored = tmp_path / "timestamp.tsr"
    stored.write_bytes(token.response)
    result = local_tsa.verify(stored.read_bytes(), digest=content_hash)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"Verification: OK" in result.stdout

    data_file = tmp_path / "manifest.json"
    data_file.write_bytes(manifest)
    by_data = local_tsa.run(
        "ts", "-verify", "-data", str(data_file), "-in", str(stored), "-CAfile", str(local_tsa.ca_pem)
    )
    assert by_data.returncode == 0, by_data.stderr.decode(errors="replace")

    assert token.tsa_url == TSA_URL
    assert token.policy == "1.2.3.4.1"
    assert token.serial.startswith("0x")
    assert abs(token.gen_time - datetime.now(UTC)) < timedelta(minutes=5)
    text = local_tsa.run("ts", "-reply", "-in", str(stored), "-text").stdout.decode()
    assert f"Serial number: {token.serial}" in text


async def test_openssl_rejects_the_token_for_another_hash(local_tsa: LocalTsa) -> None:
    digest = hashlib.sha256(b"registered manifest").digest()
    token = await TsaClient([TSA_URL], transport=local_tsa.transport()).timestamp(digest)
    other = hashlib.sha256(b"registered manifest, one byte edited").digest()
    assert local_tsa.verify(token.response, digest=other).returncode != 0


async def test_openssl_rejects_a_token_from_an_untrusted_tsa(local_tsa: LocalTsa, tmp_path: Path) -> None:
    stranger = LocalTsa.create(tmp_path / "stranger")
    digest = hashlib.sha256(b"x").digest()
    token = await TsaClient([TSA_URL], transport=stranger.transport()).timestamp(digest)
    assert stranger.verify(token.response, digest=digest).returncode == 0
    assert local_tsa.verify(token.response, digest=digest).returncode != 0


async def test_ecdsa_tsa_tokens_are_accepted(tmp_path: Path) -> None:
    ec_tsa = LocalTsa.create(tmp_path / "ec", key_type="ec")
    digest = hashlib.sha256(b"ec").digest()
    token = await TsaClient([TSA_URL], transport=ec_tsa.transport()).timestamp(digest)
    assert ec_tsa.verify(token.response, digest=digest).returncode == 0


async def test_fallback_tsa_is_used_when_the_primary_fails(local_tsa: LocalTsa) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "primary.test":
            return httpx.Response(503)
        return local_tsa.handler(request)

    client = TsaClient(["http://primary.test/tsr", "http://fallback.test/tsr"], transport=httpx.MockTransport(handler))
    digest = hashlib.sha256(b"fallback").digest()
    token = await client.timestamp(digest)
    assert token.tsa_url == "http://fallback.test/tsr"
    assert calls == ["http://primary.test/tsr", "http://fallback.test/tsr"]
    assert local_tsa.verify(token.response, digest=digest).returncode == 0
