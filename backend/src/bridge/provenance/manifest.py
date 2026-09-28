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
Numbers in the Tier-2 document follow RFC 8785 (IEEE 754 doubles; integers beyond 2**53 are refused).
"""

from __future__ import annotations

import hashlib
import hmac
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


def canonicalize(document: Mapping[str, Any]) -> bytes:
    try:
        return rfc8785.dumps(document)
    except rfc8785.CanonicalizationError as exc:
        raise ManifestError(f"the manifest cannot be canonicalised: {exc}") from exc


def build_manifest(inp: ManifestInput) -> Manifest:
    document = manifest_document(inp)
    canonical = canonicalize(document)
    return Manifest(document, canonical, hashlib.sha256(canonical).digest())


def matches(canonical: bytes, content_hash: bytes) -> bool:
    """True when ``canonical`` hashes to ``content_hash`` (one edited byte makes it False; AC-IP-2)."""
    return hmac.compare_digest(hashlib.sha256(canonical).digest(), content_hash)
