"""Registration manifest v1 (REQ-PROV-01; docs/spec/06 6.4 item 1; ADR-003).

The manifest is the RFC 8785 (JSON Canonicalization Scheme) serialisation of one registered version:

- ``manifest_version`` ("1"), ``proposal_id``, ``version_id``, ``version_no``, ``cert_id``, ``registered_at``
  (RFC 3339 UTC, microseconds; the authoritative time is the RFC 3161 token's) and ``prev_version_hash`` (hex of the
  previous registered version's ``content_hash``, or null for the first version);
- ``tier1``: the Tier-1 snapshot (title, niche, country, county, maturity, ask, problem statement, impact claims,
  summary) and the linked problem ids;
- ``tier2``: the version's Tier-2 document, a JSON object, exactly as sealed in ``proposal_confidential``;
- ``attachments``: id, SHA-256, size and content type of every attachment (file names and object keys stay inside
  the Tier-2 document);
- ``owners``: owner refs ``SHA-256(subject_salt || user_id bytes)`` with their split in basis points (one owner at
  10000 in Release 1), never names: names are resolved when a certificate is rendered;
- ``attestations``: id, text version and text SHA-256 of the ownership attestations made at registration.

``content_hash = SHA-256(canonical bytes)``. Ids are lowercase UUID strings, hashes lowercase hex, lists sorted, so
the same inputs always give the same bytes; the golden fixtures in ``tests/fixtures/provenance/`` freeze this. Any
change to the fields or their encoding is a new ``manifest_version`` with new fixtures (ADR-003 consequences).
Numbers in the Tier-2 document follow RFC 8785 (IEEE 754 doubles; integers beyond 2**53 are refused). A refusal
names the field path and the kind of value, never the value: Tier-2 content must not reach exceptions or job logs.
The keys of the Tier-2 document are the owner's (content too), so below ``manifest.tier2`` a path gives positions
(``manifest.tier2.<key 0>[1]``); only the fields the manifest itself defines are named.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import rfc8785

MANIFEST_VERSION = "1"
FULL_SPLIT_BPS = 10_000


class ManifestError(ValueError):
    """The inputs cannot form a manifest (missing hash, bad owner split, a value RFC 8785 cannot encode)."""


@dataclass(frozen=True, slots=True)
class Tier1:
    title: str
    niche_id: UUID
    country: str
    county_code: str | None
    maturity: str
    ask: str
    problem_statement: str
    impact_claims: str | None
    summary: str
    problem_ids: Sequence[UUID]


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    id: UUID
    sha256: bytes
    size_bytes: int | None
    content_type: str


@dataclass(frozen=True, slots=True)
class AttestationRef:
    id: UUID
    text_version: str
    text_sha256: bytes


@dataclass(frozen=True, slots=True)
class OwnerRef:
    ref: bytes  # SHA-256(subject_salt || user_id bytes)
    split_bps: int = FULL_SPLIT_BPS


@dataclass(frozen=True, slots=True)
class ManifestInput:
    proposal_id: UUID
    version_id: UUID
    version_no: int
    cert_id: str
    registered_at: datetime
    prev_version_hash: bytes | None
    tier1: Tier1
    tier2: Mapping[str, Any]
    attachments: Sequence[AttachmentRef] = ()
    owners: Sequence[OwnerRef] = ()
    attestations: Sequence[AttestationRef] = ()


@dataclass(frozen=True, slots=True)
class Manifest:
    document: dict[str, Any]
    canonical: bytes = field(repr=False)
    content_hash: bytes


def owner_ref(subject_salt: bytes, user_id: UUID) -> bytes:
    """``SHA-256(subject_salt || user_id)`` over the 16 raw bytes of the id (docs/spec/06 6.4 item 1)."""
    return hashlib.sha256(subject_salt + user_id.bytes).digest()


def rfc3339_utc(ts: datetime) -> str:
    if ts.tzinfo is None:
        raise ManifestError("timestamps in a manifest must be timezone-aware")
    return ts.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256_hex(value: bytes, what: str) -> str:
    if len(value) != 32:
        raise ManifestError(f"{what} must be a 32-byte SHA-256 digest")
    return value.hex()


def manifest_document(inp: ManifestInput) -> dict[str, Any]:
    """The manifest as a JSON-ready dict (before canonicalisation)."""
    if not inp.owners or sum(o.split_bps for o in inp.owners) != FULL_SPLIT_BPS:
        raise ManifestError("owner splits must add up to 10000 basis points")
    if not inp.tier1.problem_ids:
        raise ManifestError("a registered version links at least one problem")
    if not isinstance(inp.tier2, Mapping):
        raise ManifestError("the Tier-2 document must be a JSON object")
    t1 = inp.tier1
    return {
        "manifest_version": MANIFEST_VERSION,
        "proposal_id": str(inp.proposal_id),
        "version_id": str(inp.version_id),
        "version_no": inp.version_no,
        "cert_id": inp.cert_id,
        "registered_at": rfc3339_utc(inp.registered_at),
        "prev_version_hash": (
            None if inp.prev_version_hash is None else _sha256_hex(inp.prev_version_hash, "prev_version_hash")
        ),
        "tier1": {
            "title": t1.title,
            "niche_id": str(t1.niche_id),
            "country": t1.country,
            "county_code": t1.county_code,
            "maturity": t1.maturity,
            "ask": t1.ask,
            "problem_statement": t1.problem_statement,
            "impact_claims": t1.impact_claims,
            "summary": t1.summary,
            "problem_ids": sorted(str(p) for p in t1.problem_ids),
        },
        "tier2": dict(inp.tier2),
        "attachments": [
            {
                "id": str(a.id),
                "sha256": _sha256_hex(a.sha256, "attachment sha256"),
                "size_bytes": a.size_bytes,
                "content_type": a.content_type,
            }
            for a in sorted(inp.attachments, key=lambda a: str(a.id))
        ],
        "owners": sorted(
            ({"ref": _sha256_hex(o.ref, "owner ref"), "split_bps": o.split_bps} for o in inp.owners),
            key=lambda o: str(o["ref"]),
        ),
        "attestations": [
            {"id": str(a.id), "text_version": a.text_version, "text_sha256": _sha256_hex(a.text_sha256, "text_sha256")}
            for a in sorted(inp.attestations, key=lambda a: str(a.id))
        ],
    }


_INT_LIMIT = 2**53 - 1  # RFC 8785 numbers are IEEE 754 doubles
_TIER2 = "tier2"
# Every key manifest_document writes outside the Tier-2 document: the only keys an error may name.
_MANIFEST_FIELDS = frozenset(
    {
        "manifest_version",
        "proposal_id",
        "version_id",
        "version_no",
        "cert_id",
        "registered_at",
        "prev_version_hash",
        "tier1",
        _TIER2,
        "attachments",
        "owners",
        "attestations",
        *Tier1.__dataclass_fields__,
        *AttachmentRef.__dataclass_fields__,
        *OwnerRef.__dataclass_fields__,
        *AttestationRef.__dataclass_fields__,
    }
)


def _valid_text(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _key_path(path: str, key: object, position: int, *, owned: bool) -> str:
    """``path.key`` for a field the manifest defines; ``path.<key n>`` for any key of the owner's Tier-2 document
    (``owned``), whatever it looks like, and for anything else."""
    return f"{path}.{key}" if not owned and key in _MANIFEST_FIELDS else f"{path}.<key {position}>"


def _unencodable(value: Any, path: str, *, owned: bool = False) -> tuple[str, str] | None:
    """Where the first value RFC 8785 cannot encode sits, and what kind of value it is: never the value itself.
    ``owned``: ``value`` is (inside) the Tier-2 document, whose keys are never printed."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return None if _valid_text(value) else (path, "a string that is not valid Unicode")
    if isinstance(value, int):
        return None if -_INT_LIMIT <= value <= _INT_LIMIT else (path, "an integer beyond 2**53")
    if isinstance(value, float):
        return None if math.isfinite(value) else (path, "a non-finite number")
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            if (found := _unencodable(item, f"{path}[{index}]", owned=owned)) is not None:
                return found
        return None
    if isinstance(value, dict):
        for position, (key, item) in enumerate(value.items()):
            where = _key_path(path, key, position, owned=owned)
            if not isinstance(key, str) or not _valid_text(key):
                return where, "a key that is not a valid Unicode string"
            below_tier2 = owned or (path == "manifest" and key == _TIER2)
            if (found := _unencodable(item, where, owned=below_tier2)) is not None:
                return found
        return None
    return path, f"a value of unsupported type {type(value).__name__}"


def canonicalize(document: Mapping[str, Any]) -> bytes:
    """RFC 8785 bytes of ``document``. A failure names the field path and the kind of value, never the value (Tier-2
    values would otherwise reach job logs), and carries no library exception, whose attributes hold the value."""
    try:
        return rfc8785.dumps(document)
    except (ValueError, TypeError, RecursionError):  # CanonicalizationError, UnicodeError (keys), deep nesting
        pass
    try:
        found = _unencodable(document, "manifest")
    except RecursionError:
        found = None
    where, what = found or ("manifest", "nested too deeply to encode")
    raise ManifestError(f"the manifest cannot be canonicalised: {where} is {what}")


def build_manifest(inp: ManifestInput) -> Manifest:
    document = manifest_document(inp)
    canonical = canonicalize(document)
    return Manifest(document, canonical, hashlib.sha256(canonical).digest())


def matches(canonical: bytes, content_hash: bytes) -> bool:
    """True when ``canonical`` hashes to ``content_hash`` (one edited byte makes it False; AC-IP-2)."""
    return hmac.compare_digest(hashlib.sha256(canonical).digest(), content_hash)
