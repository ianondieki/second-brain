"""REQ-PROV-02 / AC-IP-1: the public verify API (lookup, token download, upload match), the published keys, and the
owner-only certificate PDF and manifest download. Public answers carry the evidence only: never the owner or title."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.db import create_session_factory
from bridge.main import create_app
from bridge.notifications.email import FakeEmailProvider
from bridge.provenance.certificate import FOOTER
from bridge.provenance.service import hash_manifest, sign_manifest, timestamp_manifest
from bridge.provenance.signing import LocalSigner, manifest_message, verify_signature
from bridge.provenance.tsa import TsaClient
from bridge.provenance.verify import LOOKUPS_PER_MINUTE, MAX_UPLOAD_BYTES, UPLOADS_PER_MINUTE
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.api import sign_in_as
from tests.integration.provenance.builders import TIER2, Built, registered_version
from tests.openssl_tsa import LocalTsa
from tests.unit.provenance.test_certificate import pdf_text

Sessions = async_sessionmaker[AsyncSession]


def app_settings(kek: bytes | None) -> Settings:
    update: dict[str, Any] = {
        "public_base_url": "https://bridge.test",
        "tier2_local_kek": None if kek is None else SecretStr(base64.b64encode(kek).decode()),
    }
    return get_settings().model_copy(update=update)


@asynccontextmanager
async def client(app_engine: AsyncEngine, kek: bytes | None) -> AsyncIterator[httpx.AsyncClient]:
    """An in-process client from its own address, so the per-IP limits of one test never touch another."""
    app = create_app(app_settings(kek))
    app.state.engine = app_engine
    app.state.session_factory = create_session_factory(app_engine)
    app.state.email_provider = FakeEmailProvider()
    address = f"10.{secrets.randbelow(250)}.{secrets.randbelow(250)}.{secrets.randbelow(250) + 1}"
    transport = httpx.ASGITransport(app=app, client=(address, 40000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
        c.app = app  # type: ignore[attr-defined]
        c.headers["X-CSRF-Token"] = (await c.get("/api/auth/csrf")).json()["csrf_token"]
        yield c


@pytest.fixture
async def registered(
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    signer: LocalSigner,
    tsa: TsaClient,
) -> Built:
    built = await registered_version(owner_engine, wrapper, attachments=1)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with sessions() as s:
        await sign_manifest(s, built.version_id, built.owner_id, signer=signer)
    async with sessions() as s:
        await timestamp_manifest(s, built.version_id, built.owner_id, tsa=tsa)
    return built


async def test_the_signing_keys_are_published(app_engine: AsyncEngine, signer: LocalSigner) -> None:
    async with client(app_engine, None) as c:
        response = await c.get("/.well-known/provenance-keys.json")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    keys = {k["kid"]: k for k in response.json()["keys"]}
    key = keys[signer.key_id]
    assert (key["kty"], key["crv"], key["alg"]) == ("OKP", "Ed25519", "EdDSA")
    assert base64.urlsafe_b64decode(key["x"] + "=") == signer.public_key
    pem_key = load_pem_public_key(key["pem"].encode())
    assert pem_key.public_bytes_raw() == signer.public_key  # type: ignore[union-attr]
    assert key["retired_at"] is None


async def test_a_public_lookup_shows_the_evidence_and_nothing_personal(
    app_engine: AsyncEngine, registered: Built, signer: LocalSigner
) -> None:
    async with client(app_engine, None) as c:
        response = await c.get(f"/api/verify/{registered.cert_id}")
        missing = await c.get("/api/verify/ZZZZZZZZZZZZZZZZ")
        malformed = await c.get("/api/verify/not-a-cert!")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "cert_id",
        "status",
        "status_label",
        "content_hash",
        "timestamp",
        "tsa_serial",
        "key_id",
        "signature",
    }
    assert body["status"] == "timestamped"
    assert body["status_label"] == "Timestamped"
    assert body["tsa_serial"].startswith("0x")
    assert body["timestamp"] is not None
    assert verify_signature(
        signer.public_key, manifest_message(bytes.fromhex(body["content_hash"])), base64.b64decode(body["signature"])
    )
    assert "Cold-chain" not in response.text
    assert "dev-" not in response.text
    assert str(registered.owner_id) not in response.text
    assert missing.status_code == 404
    assert malformed.status_code == 422


async def test_the_stored_token_downloads_and_verifies(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, registered: Built, local_tsa: LocalTsa, wrapper: LocalKeyWrapper
) -> None:
    pending = await registered_version(owner_engine, wrapper, attachments=0)  # registered, pipeline never ran
    async with client(app_engine, None) as c:
        response = await c.get(f"/api/verify/{registered.cert_id}/timestamp.tsr")
        lookup = (await c.get(f"/api/verify/{registered.cert_id}")).json()
        not_yet = await c.get(f"/api/verify/{pending.cert_id}/timestamp.tsr")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/timestamp-reply"
    assert local_tsa.verify(response.content, digest=bytes.fromhex(lookup["content_hash"])).returncode == 0
    assert not_yet.status_code == 404


async def test_an_uploaded_manifest_matches_its_certificate(
    app_engine: AsyncEngine, registered: Built, kek: bytes, tmp_path: Path
) -> None:
    async with client(app_engine, kek) as c:
        await sign_in_as(c, app_engine, registered.owner_id, mfa_verified=True)
        manifest = await c.get(f"/api/provenance/certificates/{registered.cert_id}/manifest.json")
        assert manifest.status_code == 200
        lookup = (await c.get(f"/api/verify/{registered.cert_id}")).json()
        assert hashlib.sha256(manifest.content).hexdigest() == lookup["content_hash"]

        edited = bytearray(manifest.content)
        edited[10] ^= 0x01
        match = await c.post("/api/verify", content=manifest.content)
        against_cert = await c.post(f"/api/verify?cert_id={registered.cert_id}", content=manifest.content)
        no_match = await c.post("/api/verify", content=bytes(edited))
        wrong_for_cert = await c.post(f"/api/verify?cert_id={registered.cert_id}", content=bytes(edited))
        unknown_cert = await c.post("/api/verify?cert_id=ZZZZZZZZZZZZZZZZ", content=manifest.content)
    assert match.json()["match"] is True
    assert match.json()["certificate"]["cert_id"] == registered.cert_id
    assert against_cert.json()["match"] is True
    assert no_match.json() == {"match": False, "content_hash": hashlib.sha256(edited).hexdigest(), "certificate": None}
    assert wrong_for_cert.json()["match"] is False
    assert wrong_for_cert.json()["certificate"] is None
    assert unknown_cert.status_code == 404


async def test_oversized_uploads_are_refused(app_engine: AsyncEngine) -> None:
    async with client(app_engine, None) as c:
        declared = await c.post("/api/verify", content=b"x" * (MAX_UPLOAD_BYTES + 1))

        async def body() -> AsyncIterator[bytes]:
            for _ in range(11):
                yield b"x" * (1024 * 1024)

        streamed = await c.post("/api/verify", content=body())
    assert declared.status_code == 413
    assert streamed.status_code == 413


async def test_lookups_and_uploads_are_rate_limited(app_engine: AsyncEngine) -> None:
    async with client(app_engine, None) as c:
        lookups = [(await c.get("/api/verify/ZZZZZZZZZZZZZZZZ")).status_code for _ in range(LOOKUPS_PER_MINUTE + 1)]
        uploads = [(await c.post("/api/verify", content=b"x")).status_code for _ in range(UPLOADS_PER_MINUTE + 1)]
    assert lookups[:LOOKUPS_PER_MINUTE] == [404] * LOOKUPS_PER_MINUTE
    assert lookups[-1] == 429
    assert uploads[:UPLOADS_PER_MINUTE] == [200] * UPLOADS_PER_MINUTE
    assert uploads[-1] == 429


async def test_the_certificate_is_owner_only_and_names_only_d2_owners(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, registered: Built, wrapper: LocalKeyWrapper
) -> None:
    stranger = await registered_version(owner_engine, wrapper, register=False)
    path = f"/api/provenance/certificates/{registered.cert_id}/certificate.pdf"
    async with client(app_engine, None) as anonymous:
        assert (await anonymous.get(path)).status_code == 401
    async with client(app_engine, None) as other:
        await sign_in_as(other, app_engine, stranger.owner_id, mfa_verified=True)
        assert (await other.get(path)).status_code == 404
        assert (await other.get(path.replace("certificate.pdf", "manifest.json"))).status_code == 404
    async with client(app_engine, None) as owner:
        await sign_in_as(owner, app_engine, registered.owner_id, mfa_verified=True)
        handle_pdf = await owner.get(path)
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE developer_profiles SET verification_level = 'd2' WHERE user_id = :u"),
                {"u": registered.owner_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO kyc_reviews (id, user_id, status, verified_legal_name, decided_at)"
                    " VALUES (gen_random_uuid(), :u, 'approved', 'Wanjiru Kamau', now())"
                ),
                {"u": registered.owner_id},
            )
        legal_pdf = await owner.get(path)
        no_kek = await owner.get(path.replace("certificate.pdf", "manifest.json"))
    assert handle_pdf.status_code == 200
    assert handle_pdf.headers["content-type"] == "application/pdf"
    handle_text = pdf_text(handle_pdf.content)
    assert FOOTER in handle_text
    assert registered.cert_id in handle_text
    assert "(handle)" in handle_text
    assert "Wanjiru" not in handle_text
    assert "Wanjiru Kamau (verified legal name)" in pdf_text(legal_pdf.content)
    assert no_kek.status_code == 503


async def test_the_manifest_is_not_served_before_it_is_stored(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    sessions: Sessions,
    wrapper: LocalKeyWrapper,
    store: InMemoryObjectStore,
    kek: bytes,
) -> None:
    built = await registered_version(owner_engine, wrapper, attachments=0)
    async with sessions() as s:
        await hash_manifest(s, built.version_id, built.owner_id, wrapper=wrapper, store=store)
    async with owner_engine.begin() as conn:  # simulate a record whose manifest never reached the Tier-2 row
        await conn.execute(text("ALTER TABLE proposal_confidential DISABLE TRIGGER USER"))
        await conn.execute(
            text(
                "UPDATE proposal_confidential SET manifest_ciphertext = NULL, manifest_nonce = NULL"
                " WHERE version_id = :v"
            ),
            {"v": built.version_id},
        )
        await conn.execute(text("ALTER TABLE proposal_confidential ENABLE TRIGGER USER"))
    async with client(app_engine, kek) as c:
        await sign_in_as(c, app_engine, built.owner_id, mfa_verified=True)
        response = await c.get(f"/api/provenance/certificates/{built.cert_id}/manifest.json")
        pdf = await c.get(f"/api/provenance/certificates/{built.cert_id}/certificate.pdf")
    assert response.status_code == 404
    assert "Timestamp pending" in pdf_text(pdf.content)


async def download_events(engine: AsyncEngine, version_id: UUID) -> list[Any]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    text(
                        "SELECT e.id, e.action, e.chain_id, e.actor_kind::text, e.actor_user_id, e.org_id,"
                        " e.subject_type, e.subject_id, e.payload, d.event_id AS details"
                        " FROM audit_events e LEFT JOIN event_details d ON d.event_id = e.id"
                        " WHERE e.subject_id = :v AND e.action LIKE 'provenance.%' ORDER BY e.chain_id, e.seq"
                    ),
                    {"v": version_id},
                )
            ).all()
        )


async def test_the_owners_downloads_are_audited_with_ids_only(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, registered: Built, kek: bytes
) -> None:
    """Every read of the manifest (Tier 2, read as tier2_reader) and of the certificate writes an audit event on the
    owner's chain, committed before the bytes leave: the certificate id only, no Tier-2 text, title or name."""
    base = f"/api/provenance/certificates/{registered.cert_id}"
    async with client(app_engine, kek) as c:
        await sign_in_as(c, app_engine, registered.owner_id, mfa_verified=True)
        manifest = await c.get(f"{base}/manifest.json")
        pdf = await c.get(f"{base}/certificate.pdf")
        again = await c.get(f"{base}/manifest.json")
    assert (manifest.status_code, pdf.status_code, again.status_code) == (200, 200, 200)
    events = await download_events(owner_engine, registered.version_id)
    assert sorted(e.action for e in events) == [
        "provenance.certificate_downloaded",
        "provenance.manifest_downloaded",
        "provenance.manifest_downloaded",
    ]
    for event in events:
        assert event.chain_id == f"user:{registered.owner_id}"
        assert (event.actor_kind, event.actor_user_id, event.org_id) == ("user", registered.owner_id, None)
        assert event.subject_type == "proposal_version"
        assert event.payload == {"cert_id": registered.cert_id}
        assert event.details is None
        assert TIER2["how"] not in json.dumps(event.payload)


async def test_refused_or_failed_downloads_write_no_audit_event(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, registered: Built, wrapper: LocalKeyWrapper, kek: bytes
) -> None:
    stranger = await registered_version(owner_engine, wrapper, register=False)
    base = f"/api/provenance/certificates/{registered.cert_id}"
    async with client(app_engine, kek) as other:
        await sign_in_as(other, app_engine, stranger.owner_id, mfa_verified=True)
        assert (await other.get(f"{base}/manifest.json")).status_code == 404
        assert (await other.get(f"{base}/certificate.pdf")).status_code == 404
    async with client(app_engine, None) as owner:  # no key wrapper: the manifest cannot be opened
        await sign_in_as(owner, app_engine, registered.owner_id, mfa_verified=True)
        assert (await owner.get(f"{base}/manifest.json")).status_code == 503
    assert await download_events(owner_engine, registered.version_id) == []
