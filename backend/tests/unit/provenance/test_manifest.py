"""REQ-PROV-01 / AC-IP-1 (manifest half): the RFC 8785 manifest is frozen by golden fixtures, and SHA-256 recomputed
from the stored canonical bytes equals ``content_hash``.

Golden files in ``tests/fixtures/provenance/``: ``<name>.input.json`` (the inputs), ``<name>.canonical.json`` (the
exact canonical bytes) and ``<name>.sha256`` (the content hash). A change that alters any of them is a new
``manifest_version`` (ADR-003), never an edit of these files.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from bridge.provenance.manifest import (
    MANIFEST_VERSION,
    AttachmentRef,
    AttestationRef,
    ManifestError,
    ManifestInput,
    OwnerRef,
    Tier1,
    build_manifest,
    canonicalize,
    matches,
    owner_ref,
    rfc3339_utc,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "provenance"
GOLDEN = ["manifest_v1_basic", "manifest_v1_unicode"]


def load_input(name: str) -> ManifestInput:
    raw: dict[str, Any] = json.loads((FIXTURES / f"{name}.input.json").read_text(encoding="utf-8"))
    t1 = raw["tier1"]
    return ManifestInput(
        proposal_id=UUID(raw["proposal_id"]),
        version_id=UUID(raw["version_id"]),
        version_no=raw["version_no"],
        cert_id=raw["cert_id"],
        registered_at=datetime.fromisoformat(raw["registered_at"]),
        prev_version_hash=bytes.fromhex(raw["prev_version_hash"]) if raw["prev_version_hash"] else None,
        tier1=Tier1(
            title=t1["title"],
            niche_id=UUID(t1["niche_id"]),
            country=t1["country"],
            county_code=t1["county_code"],
            maturity=t1["maturity"],
            ask=t1["ask"],
            problem_statement=t1["problem_statement"],
            impact_claims=t1["impact_claims"],
            summary=t1["summary"],
            problem_ids=[UUID(p) for p in t1["problem_ids"]],
        ),
        tier2=raw["tier2"],
        attachments=[
            AttachmentRef(UUID(a["id"]), bytes.fromhex(a["sha256"]), a["size_bytes"], a["content_type"])
            for a in raw["attachments"]
        ],
        owners=[
            OwnerRef(owner_ref(bytes.fromhex(o["subject_salt"]), UUID(o["user_id"])), o["split_bps"])
            for o in raw["owners"]
        ],
        attestations=[
            AttestationRef(UUID(a["id"]), a["text_version"], bytes.fromhex(a["text_sha256"]))
            for a in raw["attestations"]
        ],
    )


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_manifest_bytes_and_hash_are_frozen(name: str) -> None:
    manifest = build_manifest(load_input(name))
    assert manifest.canonical == (FIXTURES / f"{name}.canonical.json").read_bytes()
    expected_hash = (FIXTURES / f"{name}.sha256").read_text(encoding="ascii").strip()
    assert manifest.content_hash.hex() == expected_hash


@pytest.mark.parametrize("name", GOLDEN)
def test_recomputing_sha256_from_the_stored_manifest_equals_content_hash(name: str) -> None:
    """AC-IP-1: anyone holding the stored manifest bytes recomputes the registered hash with plain SHA-256."""
    stored = (FIXTURES / f"{name}.canonical.json").read_bytes()
    content_hash = bytes.fromhex((FIXTURES / f"{name}.sha256").read_text(encoding="ascii").strip())
    assert hashlib.sha256(stored).digest() == content_hash
    assert matches(stored, content_hash)
    assert json.loads(stored)["manifest_version"] == MANIFEST_VERSION


def test_the_canonical_form_is_order_and_whitespace_independent() -> None:
    inp = load_input("manifest_v1_basic")
    reordered = ManifestInput(
        **{
            **{f: getattr(inp, f) for f in inp.__dataclass_fields__},
            "attachments": list(reversed(inp.attachments)),
            "tier2": dict(reversed(list(inp.tier2.items()))),
            "registered_at": inp.registered_at.astimezone(UTC),
        }
    )
    assert build_manifest(reordered).canonical == build_manifest(inp).canonical
    assert b" " not in build_manifest(inp).canonical.split(b'"')[0]


def test_the_manifest_carries_refs_and_hashes_never_names() -> None:
    document = build_manifest(load_input("manifest_v1_basic")).document
    assert set(document) == {
        "manifest_version",
        "proposal_id",
        "version_id",
        "version_no",
        "cert_id",
        "registered_at",
        "prev_version_hash",
        "tier1",
        "tier2",
        "attachments",
        "owners",
        "attestations",
    }
    salt = bytes(range(32))
    user = UUID("01923f6e-0000-7000-8000-0000000000aa")
    assert document["owners"] == [{"ref": hashlib.sha256(salt + user.bytes).hexdigest(), "split_bps": 10000}]
    assert str(user) not in json.dumps(document)
    assert document["tier1"]["problem_ids"] == sorted(document["tier1"]["problem_ids"])
    assert document["registered_at"] == "2026-09-28T06:15:30.123456Z"


def test_rfc8785_reference_vector() -> None:
    """RFC 8785 section 3.2.3: the library canonicalises the RFC's own example exactly."""
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
        "string": "\u20ac$\u000f\u000aA'\u0042\u0022\u005c\\\"/",
        "literals": [None, True, False],
    }
    expected = (
        '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],'
        '"string":"\u20ac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
    )
    assert canonicalize(value) == expected.encode("utf-8")


def _with(**changes: Any) -> ManifestInput:
    inp = load_input("manifest_v1_basic")
    return ManifestInput(**{**{f: getattr(inp, f) for f in inp.__dataclass_fields__}, **changes})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"owners": []}, "owner splits"),
        ({"owners": [OwnerRef(bytes(32), 5000)]}, "owner splits"),
        ({"tier2": ["not", "an", "object"]}, "JSON object"),
        ({"tier2": {"too_big": 2**60}}, "cannot be canonicalised"),
        ({"tier2": {"nan": float("nan")}}, "cannot be canonicalised"),
        ({"prev_version_hash": b"short"}, "prev_version_hash"),
        ({"registered_at": datetime(2026, 1, 1)}, "timezone-aware"),  # noqa: DTZ001 - the error under test
        ({"attachments": [AttachmentRef(uuid4(), b"x", 1, "text/plain")]}, "attachment sha256"),
    ],
)
def test_malformed_inputs_are_refused(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ManifestError, match=message):
        build_manifest(_with(**changes))


def test_a_version_without_problems_is_refused() -> None:
    inp = load_input("manifest_v1_basic")
    tier1 = Tier1(**{**{f: getattr(inp.tier1, f) for f in inp.tier1.__dataclass_fields__}, "problem_ids": []})
    with pytest.raises(ManifestError, match="at least one problem"):
        build_manifest(_with(tier1=tier1))


def test_rfc3339_utc_normalises_offsets() -> None:
    eat = timezone(timedelta(hours=3))
    assert rfc3339_utc(datetime(2026, 9, 28, 3, 0, tzinfo=eat)) == "2026-09-28T00:00:00.000000Z"
