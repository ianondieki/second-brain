"""A version's Tier-2 document (docs/spec/06 6.1; ADR-007): approach, architecture, pricing, notes, demo and repo
links, and the attachments' file names and object keys, as one UTF-8 JSON object sealed under the proposal's data key
(``bridge.crypto.envelope``, ``Purpose.TIER2``) in ``proposal_confidential``.

``bridge_app`` has no privilege on that table: every read and write here runs as ``tier2_reader``
(``bridge.db.as_role``), whose policies admit the bound owner's rows (and, from T2.5, granted viewers' reads). Callers
check ownership first and bind the tenant. The plaintext never leaves memory: no log line, audit payload or error
carries it (a decoding failure is raised without the decoder's exception, which would hold the text).

A draft's document may carry a ``draft`` object (the "Describe a new problem" text until publishing creates the
Problem); publishing removes it before the version is registered, so it never reaches a manifest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.crypto.envelope import (
    DataKey,
    KeyWrapper,
    Purpose,
    Sealed,
    new_data_key,
    open_data_key,
    open_sealed,
    seal,
)
from bridge.db import as_role

FORMAT: Final = "bridge-tier2-v1"
TEXT_FIELDS: Final = ("approach", "architecture", "pricing", "notes")
DRAFT_KEY: Final = "draft"
ROLE: Final = "tier2_reader"


class Tier2Error(Exception):
    """A stored Tier-2 document does not decode (never carries the plaintext)."""


def empty_document() -> dict[str, Any]:
    return {"format": FORMAT, **dict.fromkeys(TEXT_FIELDS), "links": [], "attachments": []}


def encode(document: dict[str, Any]) -> bytes:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def decode(plaintext: bytes) -> dict[str, Any]:
    document: Any = None
    try:
        document = json.loads(plaintext.decode("utf-8"))
        decoded = True
    except (ValueError, RecursionError):
        decoded = False
    if not decoded or not isinstance(document, dict):
        raise Tier2Error("the Tier-2 document is not a UTF-8 JSON object")
    return document


@dataclass(slots=True)
class Document:
    """A decrypted document with the key that opens (and re-seals) it."""

    proposal_id: UUID
    version_id: UUID
    key: DataKey = field(repr=False)
    body: dict[str, Any] = field(repr=False)


_ROW = text(
    "SELECT ciphertext, nonce, wrapped_dek, kms_key_id FROM proposal_confidential"
    " WHERE version_id = :version AND proposal_id = :proposal"
)
_ANY_KEY = text("SELECT wrapped_dek, kms_key_id FROM proposal_confidential WHERE proposal_id = :proposal LIMIT 1")
_INSERT = text(
    "INSERT INTO proposal_confidential (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek, kms_key_id)"
    " VALUES (:version, :proposal, :owner, :ciphertext, :nonce, :wrapped, :key_id)"
)
_UPDATE = text(
    "UPDATE proposal_confidential SET ciphertext = :ciphertext, nonce = :nonce, updated_at = now()"
    " WHERE version_id = :version AND proposal_id = :proposal"
)


async def proposal_key(db: AsyncSession, wrapper: KeyWrapper, proposal_id: UUID) -> DataKey:
    """The proposal's data key (from any of its versions), or a fresh one for a proposal without Tier 2 yet."""
    async with as_role(db, ROLE):
        row = (await db.execute(_ANY_KEY, {"proposal": proposal_id})).one_or_none()
    if row is None:
        return await new_data_key(wrapper, proposal_id)
    return await open_data_key(wrapper, wrapped=bytes(row.wrapped_dek), key_id=row.kms_key_id, proposal_id=proposal_id)


async def load(db: AsyncSession, wrapper: KeyWrapper, proposal_id: UUID, version_id: UUID) -> Document | None:
    async with as_role(db, ROLE):
        row = (await db.execute(_ROW, {"version": version_id, "proposal": proposal_id})).one_or_none()
    if row is None:
        return None
    key = await open_data_key(wrapper, wrapped=bytes(row.wrapped_dek), key_id=row.kms_key_id, proposal_id=proposal_id)
    sealed = Sealed(bytes(row.nonce), bytes(row.ciphertext))
    plaintext = open_sealed(key, sealed, proposal_id=proposal_id, version_id=version_id, purpose=Purpose.TIER2)
    return Document(proposal_id, version_id, key, decode(plaintext))


async def save(db: AsyncSession, document: Document, *, owner_id: UUID, new: bool) -> None:
    """Seal and store the document: a new row for a new draft version, else replace the draft's ciphertext (the
    database refuses changes once the version is registered)."""
    sealed = seal(
        document.key,
        encode(document.body),
        proposal_id=document.proposal_id,
        version_id=document.version_id,
        purpose=Purpose.TIER2,
    )
    params = {
        "version": document.version_id,
        "proposal": document.proposal_id,
        "ciphertext": sealed.ciphertext,
        "nonce": sealed.nonce,
    }
    async with as_role(db, ROLE):
        if new:
            params |= {"owner": owner_id, "wrapped": document.key.wrapped, "key_id": document.key.key_id}
            await db.execute(_INSERT, params)
        else:
            await db.execute(_UPDATE, params)
