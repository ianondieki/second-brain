"""REQ-PROV-02: the signing key's public half is published in ``provenance_keys`` by the owner-role command, once,
and a different key can never be slipped in under an existing key id."""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.provenance import __main__ as cli
from bridge.provenance.signing import LocalSigner, register_public_key


@dataclass
class Impostor:
    key_id: str
    public_key: bytes

    async def sign(self, message: bytes) -> bytes:  # pragma: no cover - never called
        raise AssertionError


async def test_the_command_registers_a_key_once(database_url: URL, owner_engine: AsyncEngine) -> None:
    signer = LocalSigner(os.urandom(32))
    url = database_url.render_as_string(hide_password=False)
    assert await cli.register(url, signer) is True
    assert await cli.register(url, signer) is False
    async with owner_engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT public_key, algorithm FROM provenance_keys WHERE key_id = :k"), {"k": signer.key_id}
            )
        ).one()
    assert bytes(row.public_key) == signer.public_key
    assert row.algorithm == "ed25519"


async def test_another_key_under_an_existing_id_is_refused(owner_engine: AsyncEngine) -> None:
    signer = LocalSigner(os.urandom(32))
    async with owner_engine.begin() as conn:
        await register_public_key(conn, signer)
    impostor = Impostor(signer.key_id, LocalSigner(os.urandom(32)).public_key)
    async with owner_engine.begin() as conn:
        with pytest.raises(RuntimeError, match="different key"):
            await register_public_key(conn, impostor)


async def test_the_app_role_cannot_publish_keys(app_engine: AsyncEngine) -> None:
    from sqlalchemy.exc import DBAPIError

    async with app_engine.connect() as conn:
        with pytest.raises(DBAPIError):
            await register_public_key(conn, LocalSigner(os.urandom(32)))
