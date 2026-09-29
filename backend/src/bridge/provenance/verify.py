"""Public certificate verification (REQ-PROV-02; docs/spec/06 6.4 item 2).

``/verify`` shows only what proves the record: the content hash, the timestamp (the RFC 3161 token's time), the TSA
serial and whether an uploaded file matches, plus the signature, its key id and the ``.tsr`` token, which anyone
needs to check the record offline (``docs/runbooks/verify-offline.md``). Never the owner's name or the title: the
owner's opt-in to show them needs a schema column that does not exist yet (noted on the REQ-PROV-02 card).

Lookups are by exact certificate id (80 random bits, ``service.new_cert_id``) or by the SHA-256 of an uploaded file;
nothing lists or searches certificates. Both are rate limited per client IP on the login-attempt ledger
(``bridge.auth.throttle``), which stores only keyed digests of the IP.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth import throttle
from bridge.config import Settings
from bridge.models.enums import ProvenanceStatus

LOOKUPS_PER_MINUTE = 30
UPLOADS_PER_MINUTE = 10
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # a manifest is a few kilobytes; this leaves room and stops abuse
CERT_ID_REGEX = r"^[0-9A-Za-z]{8,24}$"


@dataclass(frozen=True, slots=True)
class PublicRecord:
    cert_id: str
    content_hash: bytes
    status: ProvenanceStatus
    tsa_time: datetime | None
    tsa_serial: str | None
    key_id: str | None
    signature: bytes | None
    tsa_token: bytes | None


_COLUMNS = "cert_id, content_hash, status, tsa_time, tsa_serial, key_id, signature, tsa_token"
_BY_CERT = text(f"SELECT {_COLUMNS} FROM provenance_records WHERE cert_id = :cert_id")  # noqa: S608 - constant
_BY_HASH = text(f"SELECT {_COLUMNS} FROM provenance_records WHERE content_hash = :digest LIMIT 1")  # noqa: S608


def _record(row: Row[Any] | None) -> PublicRecord | None:
    if row is None:
        return None
    return PublicRecord(
        cert_id=row.cert_id,
        content_hash=bytes(row.content_hash),
        status=ProvenanceStatus(row.status),
        tsa_time=row.tsa_time,
        tsa_serial=row.tsa_serial,
        key_id=row.key_id,
        signature=None if row.signature is None else bytes(row.signature),
        tsa_token=None if row.tsa_token is None else bytes(row.tsa_token),
    )


async def by_cert_id(session: AsyncSession, cert_id: str) -> PublicRecord | None:
    return _record((await session.execute(_BY_CERT, {"cert_id": cert_id})).one_or_none())


async def by_content_hash(session: AsyncSession, digest: bytes) -> PublicRecord | None:
    return _record((await session.execute(_BY_HASH, {"digest": digest})).one_or_none())


async def allow(session: AsyncSession, settings: Settings, *, purpose: str, ip: str, per_minute: int) -> bool:
    """Count one public request from ``ip`` and say whether it is within ``per_minute`` (caller commits)."""
    keys = throttle.keys(settings.secret_key.get_secret_value(), purpose, ip, ip)
    if await throttle.blocked(session, keys, pair_limit=per_minute, account_limit=per_minute, ip_limit=per_minute):
        return False
    throttle.record(session, keys, succeeded=True)
    return True
