"""Provenance routes (REQ-PROV-02, REQ-AUD-01; docs/spec/06 6.4).

Public, no session needed:

- ``GET /.well-known/provenance-keys.json``: the Ed25519 public keys (a JWK set with PEM copies) that sign manifests
  and transparency roots. Served outside ``/api``: the web server routes this path to the API.
- ``GET /api/verify/{cert_id}``: hash, timestamp, TSA serial, status, signature and key id of one certificate.
- ``GET /api/verify/{cert_id}/timestamp.tsr``: the stored RFC 3161 token, for ``openssl ts -verify``.
- ``POST /api/verify[?cert_id=]``: upload a file (raw body, <= 10 MB); its SHA-256 is matched against one certificate
  or against every registered manifest. Returns match / no match.
- ``GET /api/transparency``: the signed nightly Merkle roots over the audit chain heads.

Owner only (404 for anyone else): ``GET /api/provenance/certificates/{cert_id}/certificate.pdf`` (generated on demand,
never stored) and ``.../manifest.json`` (the registered manifest, decrypted, whose SHA-256 is the content hash). Each
download writes an audit event on the owner's chain, committed before the bytes are sent. An owner's reads of their
own Tier 2 are not gated by ``FEATURE_TIER2_ENABLED`` (a human decision, noted on the REQ-PROV-01 card).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, Path, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit import service as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep, client_ip
from bridge.config import ConfigurationError
from bridge.crypto.envelope import Purpose, Sealed, key_wrapper_from_settings, open_data_key, open_sealed
from bridge.db import as_role
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import ProvenanceStatus
from bridge.provenance import verify
from bridge.provenance.certificate import load_certificate, render_pdf
from bridge.provenance.service import status_label

router = APIRouter(tags=["provenance"], responses=ERROR_RESPONSES)

CertId = Annotated[str, Path(pattern=verify.CERT_ID_REGEX, description="Certificate id")]
PUBLIC_CACHE = "public, max-age=300"


class ProvenanceKey(BaseModel):
    kid: str
    kty: Literal["OKP"] = "OKP"
    crv: Literal["Ed25519"] = "Ed25519"
    alg: Literal["EdDSA"] = "EdDSA"
    use: Literal["sig"] = "sig"
    x: str  # base64url of the raw 32-byte public key (RFC 8037)
    pem: str
    created_at: datetime
    retired_at: datetime | None


class ProvenanceKeys(BaseModel):
    keys: list[ProvenanceKey]


class CertificateCheck(BaseModel):
    cert_id: str
    status: Literal["timestamped", "timestamp_pending"]
    status_label: str
    content_hash: str
    timestamp: datetime | None
    tsa_serial: str | None
    key_id: str | None
    signature: str | None  # base64 Ed25519 over "bridge-manifest-v1:<content_hash>"


class UploadCheck(BaseModel):
    match: bool
    content_hash: str  # SHA-256 of the uploaded bytes
    certificate: CertificateCheck | None


class TransparencyRoot(BaseModel):
    day: date
    merkle_root: str
    signature: str  # base64 Ed25519 over "bridge-transparency-root-v1:<day>:<merkle_root>"
    key_id: str


class Transparency(BaseModel):
    roots: list[TransparencyRoot]


def _check(record: verify.PublicRecord) -> CertificateCheck:
    stamped = record.status == ProvenanceStatus.TIMESTAMPED
    return CertificateCheck(
        cert_id=record.cert_id,
        status="timestamped" if stamped else "timestamp_pending",
        status_label=status_label(record.status),
        content_hash=record.content_hash.hex(),
        timestamp=record.tsa_time,
        tsa_serial=record.tsa_serial,
        key_id=record.key_id,
        signature=None if record.signature is None else base64.b64encode(record.signature).decode("ascii"),
    )


async def _throttle(db: Db, settings: SettingsDep, request: Request, *, purpose: str, per_minute: int) -> None:
    allowed = await verify.allow(db, settings, purpose=purpose, ip=client_ip(request), per_minute=per_minute)
    await db.commit()
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many checks from this address. Wait a minute and try again.")


@router.get("/.well-known/provenance-keys.json")
async def provenance_keys(db: Db, response: Response) -> ProvenanceKeys:
    """The public keys that sign manifests and transparency roots (retired keys stay listed)."""
    rows = (
        await db.execute(text("SELECT key_id, public_key, created_at, retired_at FROM provenance_keys ORDER BY key_id"))
    ).all()
    response.headers["Cache-Control"] = PUBLIC_CACHE
    keys = []
    for row in rows:
        raw = bytes(row.public_key)
        pem = Ed25519PublicKey.from_public_bytes(raw).public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        keys.append(
            ProvenanceKey(
                kid=row.key_id,
                x=base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
                pem=pem.decode("ascii"),
                created_at=row.created_at,
                retired_at=row.retired_at,
            )
        )
    return ProvenanceKeys(keys=keys)


@router.get("/api/verify/{cert_id}")
async def verify_certificate(cert_id: CertId, request: Request, db: Db, settings: SettingsDep) -> CertificateCheck:
    """Look up one certificate: hash, timestamp, TSA serial and status (never the owner or the title)."""
    await _throttle(db, settings, request, purpose="verify", per_minute=verify.LOOKUPS_PER_MINUTE)
    record = await verify.by_cert_id(db, cert_id)
    if record is None:
        raise not_found("No certificate has this id.")
    return _check(record)


@router.get(
    "/api/verify/{cert_id}/timestamp.tsr",
    response_class=Response,
    responses={200: {"content": {"application/timestamp-reply": {}}, "description": "DER TimeStampResp"}},
)
async def timestamp_token(cert_id: CertId, request: Request, db: Db, settings: SettingsDep) -> Response:
    """The certificate's RFC 3161 token (DER TimeStampResp) for ``openssl ts -verify``."""
    await _throttle(db, settings, request, purpose="verify", per_minute=verify.LOOKUPS_PER_MINUTE)
    record = await verify.by_cert_id(db, cert_id)
    if record is None or record.tsa_token is None:
        raise not_found("No timestamp token is stored for this certificate yet.")
    return Response(
        record.tsa_token,
        media_type="application/timestamp-reply",
        headers={"Content-Disposition": f'attachment; filename="{record.cert_id}.tsr"'},
    )


@router.post(
    "/api/verify",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def verify_upload(
    request: Request,
    db: Db,
    settings: SettingsDep,
    cert_id: Annotated[str | None, Query(pattern=verify.CERT_ID_REGEX)] = None,
) -> UploadCheck:
    """Hash an uploaded file (the raw request body) and say whether it matches a registered manifest."""
    await _throttle(db, settings, request, purpose="verify-upload", per_minute=verify.UPLOADS_PER_MINUTE)
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > verify.MAX_UPLOAD_BYTES:
        raise ApiError(413, "too_large", "Files up to 10 MB can be checked.")
    digest, size = hashlib.sha256(), 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > verify.MAX_UPLOAD_BYTES:
            raise ApiError(413, "too_large", "Files up to 10 MB can be checked.")
        digest.update(chunk)
    content_hash = digest.digest()
    if cert_id is not None:
        record = await verify.by_cert_id(db, cert_id)
        if record is None:
            raise not_found("No certificate has this id.")
        matched = record.content_hash == content_hash
    else:
        record = await verify.by_content_hash(db, content_hash)
        matched = record is not None
    return UploadCheck(
        match=matched,
        content_hash=content_hash.hex(),
        certificate=_check(record) if record is not None and matched else None,
    )


@router.get("/api/transparency")
async def transparency(db: Db, response: Response, limit: Annotated[int, Query(ge=1, le=366)] = 90) -> Transparency:
    """The latest signed Merkle roots over the audit chain heads, newest first (REQ-AUD-01)."""
    rows = (
        await db.execute(
            text("SELECT day, merkle_root, signature, key_id FROM transparency_roots ORDER BY day DESC LIMIT :limit"),
            {"limit": limit},
        )
    ).all()
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return Transparency(
        roots=[
            TransparencyRoot(
                day=r.day,
                merkle_root=bytes(r.merkle_root).hex(),
                signature=base64.b64encode(bytes(r.signature)).decode("ascii"),
                key_id=r.key_id,
            )
            for r in rows
        ]
    )


@router.get(
    "/api/provenance/certificates/{cert_id}/certificate.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "Authorship certificate"}},
)
async def certificate_pdf(cert_id: CertId, live: CurrentSession, db: Db, settings: SettingsDep) -> Response:
    """The authorship certificate of one of your registered versions, generated now and never stored."""
    data = await load_certificate(db, cert_id=cert_id, user_id=live.user.id, public_base_url=settings.public_base_url)
    if data is None:
        raise not_found("No certificate of yours has this id.")
    pdf = render_pdf(data)
    await _audit_download(db, CERTIFICATE_DOWNLOADED, live.user.id, data.version_id, data.cert_id)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{data.cert_id}.pdf"'},
    )


CERTIFICATE_DOWNLOADED = "provenance.certificate_downloaded"
MANIFEST_DOWNLOADED = "provenance.manifest_downloaded"


async def _audit_download(db: AsyncSession, action: str, user_id: UUID, version_id: UUID, cert_id: str) -> None:
    """Audit an owner's download on their own chain (the certificate id only: no title, name or Tier-2 text) and
    commit before the bytes are sent, so a read that cannot be recorded is not served (docs/spec/06 6.1: every
    Tier-2 read writes an audit event)."""
    await audit.record(
        db,
        action,
        actor_user_id=user_id,
        subject_type="proposal_version",
        subject_id=version_id,
        payload={"cert_id": cert_id},
    )
    await db.commit()


_OWNED_VERSION = text(
    "SELECT v.id FROM provenance_records r JOIN proposal_versions v ON v.id = r.version_id"
    " JOIN proposals p ON p.id = v.proposal_id WHERE r.cert_id = :cert_id AND p.owner_id = :user"
)
_MANIFEST = text(
    "SELECT proposal_id, version_id, wrapped_dek, kms_key_id, manifest_ciphertext, manifest_nonce"
    " FROM proposal_confidential WHERE version_id = :version"
)


@router.get(
    "/api/provenance/certificates/{cert_id}/manifest.json",
    response_class=Response,
    responses={200: {"content": {"application/json": {}}, "description": "The registered RFC 8785 manifest"}},
)
async def manifest_json(cert_id: CertId, live: CurrentSession, db: Db, settings: SettingsDep) -> Response:
    """Your registered manifest, byte for byte: its SHA-256 is the certificate's content hash."""
    version_id = (await db.execute(_OWNED_VERSION, {"cert_id": cert_id, "user": live.user.id})).scalar_one_or_none()
    if version_id is None:
        raise not_found("No certificate of yours has this id.")
    async with as_role(db, "tier2_reader"):  # the owner reads their own Tier 2 (the check above)
        row = (await db.execute(_MANIFEST, {"version": version_id})).one_or_none()
    if row is None or row.manifest_ciphertext is None:
        raise not_found("The manifest is not stored yet.")
    try:
        wrapper = key_wrapper_from_settings(settings)
    except ConfigurationError as exc:
        raise ApiError(503, "not_configured", "Manifest downloads are not available on this server.") from exc
    key = await open_data_key(
        wrapper, wrapped=bytes(row.wrapped_dek), key_id=row.kms_key_id, proposal_id=row.proposal_id
    )
    manifest = open_sealed(
        key,
        Sealed(bytes(row.manifest_nonce), bytes(row.manifest_ciphertext)),
        proposal_id=row.proposal_id,
        version_id=row.version_id,
        purpose=Purpose.MANIFEST,
    )
    await _audit_download(db, MANIFEST_DOWNLOADED, live.user.id, version_id, cert_id)
    return Response(
        manifest,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="manifest-{cert_id}.json"'},
    )
