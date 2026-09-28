"""The version registration pipeline (REQ-PROV-01; docs/spec/06 6.4 item 1; ADR-003).

Publishing registers a version: the publish flow (T2.3) marks the version ``registered`` (Tier-1 snapshot, cert id)
and calls ``enqueue_registration(session, version_id)`` in the same transaction. Three idempotent background steps
follow, each queued by the one before it in the same transaction as that step's writes (``bridge.jobs.outbox``):

1. ``hash_manifest``: build the RFC 8785 manifest (``manifest.py``) from the Tier-1 snapshot, the decrypted Tier-2
   document, attachment hashes, the owner ref and the attestations; seal it under the proposal key into
   ``proposal_confidential.manifest_ciphertext``/``manifest_nonce`` and into the ``evidence`` bucket; insert the
   ``provenance_records`` row (status ``hashed``) and fill the version's ``content_hash``, ``prev_version_hash`` and
   ``manifest_version``.
2. ``sign_manifest``: Ed25519 signature over the content hash (status ``signed``).
3. ``timestamp_manifest``: RFC 3161 token over the content hash (status ``timestamped``) and, in the same transaction,
   the ``proposal.version_registered`` audit event. Until then the record reads "Timestamp pending"; a TSA outage
   is retried with backoff (``bridge.jobs.provenance``).

Every step binds the version's owner (``bind_tenant``) and reads or writes Tier 2 and provenance records only as
``provenance_worker`` (``bridge.db.as_role``), whose policies admit only that owner's rows. Tier-2 plaintext and the
manifest never leave memory unencrypted: no log line, audit payload or ``bridge_app``-readable column holds them.
Errors: ``RegistrationError`` is permanent (not retried); ``RegistrationPendingError`` means "try again later".
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit import service as audit
from bridge.crypto.envelope import KeyWrapper, Purpose, Sealed, associated_data, open_data_key, open_sealed, seal
from bridge.db import as_role, bind_tenant
from bridge.ids import uuid7
from bridge.jobs import outbox
from bridge.models.enums import AuditActor, AvStatus, ProvenanceStatus, VersionStatus
from bridge.provenance.manifest import (
    MANIFEST_VERSION,
    AttachmentRef,
    AttestationRef,
    ManifestError,
    ManifestInput,
    OwnerRef,
    Tier1,
    build_manifest,
)
from bridge.provenance.signing import Signer, manifest_message
from bridge.provenance.tsa import TsaClient
from bridge.storage.objects import BucketName, ObjectStore

QUEUE = "provenance"
TASK_HASH = "provenance.hash_manifest"
TASK_SIGN = "provenance.sign_manifest"
TASK_TIMESTAMP = "provenance.timestamp_manifest"
EVIDENCE: BucketName = "evidence"
WORKER = "provenance_worker"
SEALED_MANIFEST_FORMAT = "bridge-sealed-manifest-v1"
REGISTERED_EVENT = "proposal.version_registered"

# Certificate ids: 16 Crockford base32 characters (80 random bits), so ids cannot be enumerated (docs/spec/06 6.4).
_CERT_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CERT_ID_PATTERN = re.compile(r"[0-9A-Za-z]{8,24}")


class RegistrationError(Exception):
    """The version cannot be registered as it stands (permanent: the job is not retried)."""


class RegistrationPendingError(Exception):
    """A precondition is not met yet (an earlier version still registering, an attachment still scanning, the signing
    key not yet published): the job is retried with backoff."""


def new_cert_id() -> str:
    """A fresh certificate id for the publish flow (T2.3) to store in ``proposal_versions.cert_id``."""
    return "".join(secrets.choice(_CERT_ALPHABET) for _ in range(16))


def status_label(status: ProvenanceStatus | None) -> str:
    """What a certificate or ``/verify`` shows: the TSA token is the evidence, so anything short of it is pending."""
    return "Timestamped" if status == ProvenanceStatus.TIMESTAMPED else "Timestamp pending"


def stage_args(version_id: UUID, owner_id: UUID) -> dict[str, str]:
    return {"version_id": str(version_id), "owner_id": str(owner_id)}


def lock_for(version_id: UUID) -> str:
    return f"provenance:{version_id}"


def advisory_key(version_id: UUID) -> int:
    """A signed 64-bit advisory lock key for one version's registration."""
    return int.from_bytes(hashlib.sha256(b"bridge.provenance|" + version_id.bytes).digest()[:8], "big", signed=True)


def evidence_key(proposal_id: UUID, version_id: UUID) -> str:
    return f"manifests/{proposal_id}/{version_id}/manifest-v{MANIFEST_VERSION}.sealed.json"


def _rowcount(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


async def _defer_next(session: AsyncSession, task: str, version_id: UUID, owner_id: UUID) -> int:
    return await outbox.defer(session, task, stage_args(version_id, owner_id), queue=QUEUE, lock=lock_for(version_id))


async def enqueue_registration(session: AsyncSession, version_id: UUID) -> int:
    """Queue the registration of a just-registered version in the caller's transaction (the publish flow's one call).

    The job exists only if the caller commits. Returns the Procrastinate job id."""
    row = (
        await session.execute(
            text(
                "SELECT v.status, p.owner_id FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id"
                " WHERE v.id = :version"
            ),
            {"version": version_id},
        )
    ).one_or_none()
    if row is None:
        raise RegistrationError(f"version {version_id} is not visible")
    if row.status != VersionStatus.REGISTERED:
        raise RegistrationError("only a registered version is registered (drafts are not evidence)")
    return await _defer_next(session, TASK_HASH, version_id, row.owner_id)


# --- the owner ref (one place: revision 0002's fix replaces the salt read with app_subject_digest) -------------------


async def subject_digest(session: AsyncSession, user_id: UUID, data: bytes) -> bytes:
    """``SHA-256(subject_salt || data)`` for one user. The owner ref is ``subject_digest(owner, owner_id.bytes)``.

    Reads ``users.subject_salt`` as ``bridge_app`` today. Revision 0002's pending fix withdraws that read and adds the
    SECURITY DEFINER ``app_subject_digest(p_user_id, p_data)``, which computes the same value in SQL; switch this one
    helper to ``SELECT app_subject_digest(:user, :data)`` when it lands."""
    salt = (
        await session.execute(text("SELECT subject_salt FROM users WHERE id = :user"), {"user": user_id})
    ).scalar_one()
    return hashlib.sha256(bytes(salt) + data).digest()


# --- step 1: manifest and hash -------------------------------------------------------------------------------------

# One registration of a version at a time, whatever else runs: a transaction-scoped advisory lock needs no privilege
# on the version row (a row lock would depend on the app role's UPDATE policy for registered versions).
_LOCK = text("SELECT pg_advisory_xact_lock(:key)")
_VERSION = text(
    "SELECT v.id, v.proposal_id, v.version_no, v.status, v.cert_id, v.registered_at, v.title, v.niche_id, v.country,"
    " v.county_code, v.maturity, v.ask, v.problem_statement, v.impact_claims, v.summary, p.owner_id"
    " FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id WHERE v.id = :version"
)
_PREVIOUS = text(
    "SELECT content_hash FROM proposal_versions WHERE proposal_id = :proposal AND status = 'registered'"
    " AND version_no < :version_no ORDER BY version_no DESC LIMIT 1"
)
_PROBLEMS = text("SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :version")
_ATTACHMENTS = text(
    "SELECT id, sha256, size_bytes, content_type, av_status FROM proposal_attachments WHERE version_id = :version"
)
_ATTESTATIONS = text(
    "SELECT id, text_version, text_sha256 FROM attestations WHERE version_id = :version AND user_id = :owner"
)
_RECORD_EXISTS = text("SELECT 1 FROM provenance_records WHERE version_id = :version")
_TIER2 = text(
    "SELECT proposal_id, ciphertext, nonce, wrapped_dek, kms_key_id, manifest_ciphertext"
    " FROM proposal_confidential WHERE version_id = :version"
)
_STORE_MANIFEST = text(
    "UPDATE proposal_confidential SET manifest_ciphertext = :ciphertext, manifest_nonce = :nonce"
    " WHERE version_id = :version AND manifest_ciphertext IS NULL"
)
_INSERT_RECORD = text(
    "INSERT INTO provenance_records (id, version_id, cert_id, content_hash, status, evidence_s3_key)"
    " VALUES (:id, :version, :cert_id, :content_hash, 'hashed', :evidence_key)"
)
_WORKER_FILLS_VERSION = text(
    "SELECT has_column_privilege('provenance_worker', 'proposal_versions', 'content_hash', 'UPDATE')"
)
_FILL_VERSION = text(
    "UPDATE proposal_versions SET content_hash = :content_hash, prev_version_hash = :prev_hash,"
    " manifest_version = :manifest_version WHERE id = :version AND content_hash IS NULL"
)


@dataclass(frozen=True, slots=True)
class _Tier2Row:
    proposal_id: UUID
    sealed: Sealed
    wrapped_dek: bytes
    kms_key_id: str
    has_manifest: bool


async def _attachments(session: AsyncSession, version_id: UUID) -> list[AttachmentRef]:
    refs: list[AttachmentRef] = []
    for row in (await session.execute(_ATTACHMENTS, {"version": version_id})).all():
        if row.av_status in (AvStatus.INFECTED, AvStatus.FAILED):
            raise RegistrationError(f"attachment {row.id} failed its scan and cannot be registered")
        if row.av_status != AvStatus.CLEAN or row.sha256 is None:
            raise RegistrationPendingError(f"attachment {row.id} is not uploaded and scanned yet")
        refs.append(AttachmentRef(row.id, bytes(row.sha256), row.size_bytes, row.content_type))
    return refs


async def _tier2(session: AsyncSession, version_id: UUID) -> _Tier2Row:
    row = (await session.execute(_TIER2, {"version": version_id})).one_or_none()
    if row is None:
        raise RegistrationError("a registered version needs its Tier-2 row (an empty document is {})")
    sealed = Sealed(bytes(row.nonce), bytes(row.ciphertext))
    return _Tier2Row(
        row.proposal_id, sealed, bytes(row.wrapped_dek), row.kms_key_id, row.manifest_ciphertext is not None
    )


def _tier2_document(plaintext: bytes) -> dict[str, Any]:
    try:
        document = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistrationError("the Tier-2 document is not UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise RegistrationError("the Tier-2 document must be a JSON object")
    return document


def sealed_manifest_object(
    *, proposal_id: UUID, version_id: UUID, cert_id: str, content_hash: bytes, tier2: _Tier2Row, sealed: Sealed
) -> bytes:
    """The evidence object: the sealed manifest with everything needed to open it given the key wrapper."""
    body = {
        "format": SEALED_MANIFEST_FORMAT,
        "proposal_id": str(proposal_id),
        "version_id": str(version_id),
        "cert_id": cert_id,
        "content_hash": content_hash.hex(),
        "kms_key_id": tier2.kms_key_id,
        "wrapped_dek": base64.b64encode(tier2.wrapped_dek).decode("ascii"),
        "aad": associated_data(proposal_id, version_id, Purpose.MANIFEST).decode("ascii"),
        "nonce": base64.b64encode(sealed.nonce).decode("ascii"),
        "ciphertext": base64.b64encode(sealed.ciphertext).decode("ascii"),
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


async def _fill_version_hashes(session: AsyncSession, params: dict[str, Any]) -> None:
    """Fill the version's fill-once registration columns. Revision 0002 as merged grants this to the owner-bound
    ``bridge_app``; its pending fix gives it to ``provenance_worker`` only. The privilege decides, so this is right
    before and after that fix; drop the ``bridge_app`` branch once the fix is merged."""
    if (await session.execute(_WORKER_FILLS_VERSION)).scalar_one():
        async with as_role(session, WORKER):
            filled = _rowcount(await session.execute(_FILL_VERSION, params))
    else:
        filled = _rowcount(await session.execute(_FILL_VERSION, params))
    if filled != 1:
        raise RegistrationError("the version's registration hashes were already set without a provenance record")


async def hash_manifest(
    session: AsyncSession, version_id: UUID, owner_id: UUID, *, wrapper: KeyWrapper, store: ObjectStore
) -> bool:
    """Step 1. Returns False when the version already has its provenance record (nothing to do)."""
    await bind_tenant(session, user_id=owner_id)
    async with session.begin():
        await session.execute(_LOCK, {"key": advisory_key(version_id)})
        version = (await session.execute(_VERSION, {"version": version_id})).one_or_none()
        if version is None or version.owner_id != owner_id:
            raise RegistrationError(f"version {version_id} is not visible to its owner")
        if version.status != VersionStatus.REGISTERED:
            raise RegistrationError("only a registered version is registered (drafts are not evidence)")
        async with as_role(session, WORKER):
            done = (await session.execute(_RECORD_EXISTS, {"version": version_id})).first() is not None
            tier2 = None if done else await _tier2(session, version_id)
        if tier2 is None:
            return False
        if tier2.has_manifest:
            raise RegistrationError("the Tier-2 row already holds a manifest without a provenance record")
        previous = (
            await session.execute(_PREVIOUS, {"proposal": version.proposal_id, "version_no": version.version_no})
        ).one_or_none()
        if previous is not None and previous.content_hash is None:
            raise RegistrationPendingError("the previous version is still registering")
        key = await open_data_key(
            wrapper, wrapped=tier2.wrapped_dek, key_id=tier2.kms_key_id, proposal_id=version.proposal_id
        )
        where = {"proposal_id": version.proposal_id, "version_id": version_id}
        document = _tier2_document(open_sealed(key, tier2.sealed, purpose=Purpose.TIER2, **where))
        problem_ids = (await session.execute(_PROBLEMS, {"version": version_id})).scalars().all()
        attestations = (await session.execute(_ATTESTATIONS, {"version": version_id, "owner": owner_id})).all()
        try:
            manifest = build_manifest(
                ManifestInput(
                    proposal_id=version.proposal_id,
                    version_id=version_id,
                    version_no=version.version_no,
                    cert_id=version.cert_id,
                    registered_at=version.registered_at,
                    prev_version_hash=None if previous is None else bytes(previous.content_hash),
                    tier1=Tier1(
                        title=version.title,
                        niche_id=version.niche_id,
                        country=version.country,
                        county_code=version.county_code,
                        maturity=str(version.maturity),
                        ask=str(version.ask),
                        problem_statement=version.problem_statement,
                        impact_claims=version.impact_claims,
                        summary=version.summary,
                        problem_ids=list(problem_ids),
                    ),
                    tier2=document,
                    attachments=await _attachments(session, version_id),
                    owners=[OwnerRef(await subject_digest(session, owner_id, owner_id.bytes))],
                    attestations=[AttestationRef(a.id, a.text_version, bytes(a.text_sha256)) for a in attestations],
                )
            )
        except ManifestError as exc:
            raise RegistrationError(str(exc)) from exc
        sealed = seal(key, manifest.canonical, purpose=Purpose.MANIFEST, **where)
        object_key = evidence_key(version.proposal_id, version_id)
        await store.put(
            EVIDENCE,
            object_key,
            sealed_manifest_object(
                proposal_id=version.proposal_id,
                version_id=version_id,
                cert_id=version.cert_id,
                content_hash=manifest.content_hash,
                tier2=tier2,
                sealed=sealed,
            ),
            content_type="application/json",
        )
        async with as_role(session, WORKER):
            stored = await session.execute(
                _STORE_MANIFEST, {"ciphertext": sealed.ciphertext, "nonce": sealed.nonce, "version": version_id}
            )
            if _rowcount(stored) != 1:
                raise RegistrationError("the Tier-2 row already holds a manifest")
            await session.execute(
                _INSERT_RECORD,
                {
                    "id": uuid7(),
                    "version": version_id,
                    "cert_id": version.cert_id,
                    "content_hash": manifest.content_hash,
                    "evidence_key": object_key,
                },
            )
        await _fill_version_hashes(
            session,
            {
                "content_hash": manifest.content_hash,
                "prev_hash": None if previous is None else bytes(previous.content_hash),
                "manifest_version": MANIFEST_VERSION,
                "version": version_id,
            },
        )
        await _defer_next(session, TASK_SIGN, version_id, owner_id)
    return True


# --- step 2: signature ----------------------------------------------------------------------------------------------

_RECORD = text(
    "SELECT id, cert_id, content_hash, signature, key_id, status, tsa_token FROM provenance_records"
    " WHERE version_id = :version"
)
_KEY = text("SELECT retired_at FROM provenance_keys WHERE key_id = :key_id")
_SIGN = text(
    "UPDATE provenance_records SET signature = :signature, key_id = :key_id, status = 'signed'"
    " WHERE id = :id AND signature IS NULL"
)


async def sign_manifest(session: AsyncSession, version_id: UUID, owner_id: UUID, *, signer: Signer) -> bool:
    """Step 2. Returns False when the record is already signed."""
    await bind_tenant(session, user_id=owner_id)
    async with session.begin():
        async with as_role(session, WORKER):
            record = (await session.execute(_RECORD, {"version": version_id})).one_or_none()
            if record is None:
                raise RegistrationError(f"version {version_id} has no provenance record")
            if record.signature is not None:
                return False
            key = (await session.execute(_KEY, {"key_id": signer.key_id})).one_or_none()
            if key is None or key.retired_at is not None:
                raise RegistrationPendingError(
                    f"signing key {signer.key_id} is not published (python -m bridge.provenance register-key)"
                )
            signature = await signer.sign(manifest_message(bytes(record.content_hash)))
            signed = await session.execute(_SIGN, {"signature": signature, "key_id": signer.key_id, "id": record.id})
        if _rowcount(signed) == 1:
            await _defer_next(session, TASK_TIMESTAMP, version_id, owner_id)
    return _rowcount(signed) == 1


# --- step 3: RFC 3161 timestamp and the audit event -----------------------------------------------------------------

_TIMESTAMP = text(
    "UPDATE provenance_records SET tsa_token = :token, tsa_time = :tsa_time, tsa_serial = :serial, tsa_url = :url,"
    " status = 'timestamped' WHERE id = :id AND tsa_token IS NULL"
)


async def timestamp_manifest(session: AsyncSession, version_id: UUID, owner_id: UUID, *, tsa: TsaClient) -> bool:
    """Step 3. The TSA is called outside any transaction; the token and the audit event are written together.
    Returns False when the record already holds its token."""
    await bind_tenant(session, user_id=owner_id)
    async with session.begin(), as_role(session, WORKER):
        record = (await session.execute(_RECORD, {"version": version_id})).one_or_none()
    if record is None:
        raise RegistrationError(f"version {version_id} has no provenance record")
    if record.tsa_token is not None:
        return False
    if record.status == ProvenanceStatus.HASHED:
        raise RegistrationPendingError("the manifest is not signed yet")
    token = await tsa.timestamp(bytes(record.content_hash))
    async with session.begin():
        async with as_role(session, WORKER):
            stamped = _rowcount(
                await session.execute(
                    _TIMESTAMP,
                    {
                        "token": token.response,
                        "tsa_time": token.gen_time,
                        "serial": token.serial,
                        "url": token.tsa_url,
                        "id": record.id,
                    },
                )
            )
        if stamped == 1:
            await audit.record(
                session,
                REGISTERED_EVENT,
                actor_user_id=None,
                actor_kind=AuditActor.SYSTEM,
                subject_type="proposal_version",
                subject_id=version_id,
                payload={
                    "cert_id": record.cert_id,
                    "content_hash": bytes(record.content_hash).hex(),
                    "key_id": record.key_id,
                    "tsa_serial": token.serial,
                    "tsa_time": token.gen_time.isoformat(),
                },
            )
    return stamped == 1
