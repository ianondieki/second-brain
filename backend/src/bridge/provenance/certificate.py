"""Authorship certificate PDF (REQ-PROV-02; docs/spec/06 6.4 item 2; ADR-003 item 2).

Generated on demand for the version's owner and never stored: names are resolved at render time (the manifest holds
only salted owner refs), so erasure and D2 legal-name updates stay possible. The certificate shows the cert id, the
owner (verified legal name only when the owner is D2-verified, otherwise the handle) and split, the registration time
in UTC and East Africa Time (the RFC 3161 token's time once stored), the content hash, the signature and its key id,
the TSA serial or "Timestamp pending", the attachment hashes, a QR code and link to ``{PUBLIC_BASE_URL}/verify/<cert
id>``, and exactly the fixed footer of docs/spec/06 6.4 item 2. Owner text is escaped before layout.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements.calendar import NAIROBI
from bridge.models.enums import DevVerification, ProvenanceStatus
from bridge.provenance.service import status_label

# docs/spec/06 6.4 item 2, verbatim. Legal wording: never edit without the human (CLAUDE.md, ADR-003).
FOOTER = (
    "This certificate is evidence of what was submitted and when. It is not a patent, copyright registration or "
    "guarantee against independent development or misuse."
)
PENDING = "Timestamp pending"
QR_SIZE = 38 * mm


@dataclass(frozen=True, slots=True)
class CertificateData:
    cert_id: str
    version_id: UUID
    title: str
    version_no: int
    owner_name: str
    owner_is_legal_name: bool
    registered_at: datetime
    status: ProvenanceStatus
    content_hash: bytes
    signature: bytes | None
    key_id: str | None
    tsa_time: datetime | None
    tsa_serial: str | None
    verify_url: str
    split_bps: int = 10_000
    attachment_hashes: tuple[bytes, ...] = field(default=())


def utc_text(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def eat_text(ts: datetime) -> str:
    return ts.astimezone(NAIROBI).strftime("%Y-%m-%d %H:%M:%S EAT (UTC+3)")


def verify_url(public_base_url: str, cert_id: str) -> str:
    return f"{public_base_url.rstrip('/')}/verify/{cert_id}"


def _qr(url: str) -> Drawing:
    widget = QrCodeWidget(url, barLevel="M")
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(QR_SIZE, QR_SIZE, transform=[QR_SIZE / (right - left), 0, 0, QR_SIZE / (top - bottom), 0, 0])
    drawing.add(widget)
    return drawing


def render_pdf(data: CertificateData) -> bytes:
    """The certificate as PDF bytes (uncompressed content streams, so the text is plain in the file)."""
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, leading=12.5)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=8.5, leading=11, wordWrap="CJK")
    footer = ParagraphStyle("footer", parent=body, fontSize=9, leading=12, textColor=HexColor("#333333"))
    # [[COPY-REVIEW]] labels and headings of the certificate (the footer is fixed by the spec).
    moment = data.tsa_time or data.registered_at
    when = "Timestamped (RFC 3161)" if data.tsa_time else "Registered (timestamp pending)"
    owner = escape(data.owner_name) + (" (verified legal name)" if data.owner_is_legal_name else " (handle)")
    rows: list[tuple[str, Flowable]] = [
        ("Certificate id", Paragraph(escape(data.cert_id), mono)),
        ("Title", Paragraph(escape(data.title), body)),
        ("Version", Paragraph(str(data.version_no), body)),
        ("Owner", Paragraph(f"{owner}, {data.split_bps / 100:g}%", body)),
        (when, Paragraph(f"{utc_text(moment)}<br/>{eat_text(moment)}", body)),
        ("Status", Paragraph(status_label(data.status), body)),
        ("Content hash (SHA-256)", Paragraph(data.content_hash.hex(), mono)),
        ("Signature key id", Paragraph(escape(data.key_id or "Signature pending"), mono)),
        (
            "Signature (Ed25519, base64)",
            Paragraph(base64.b64encode(data.signature).decode() if data.signature else "Signature pending", mono),
        ),
        ("TSA serial", Paragraph(escape(data.tsa_serial or PENDING), mono)),
        (
            "Attachment hashes (SHA-256)",
            Paragraph("<br/>".join(h.hex() for h in data.attachment_hashes) or "No attachments", mono),
        ),
    ]
    table = Table([[Paragraph(f"<b>{label}</b>", body), value] for label, value in rows], colWidths=[48 * mm, 122 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, HexColor("#BBBBBB")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    link = escape(data.verify_url)
    story: list[Flowable] = [
        Paragraph("Authorship certificate", styles["Title"]),
        Spacer(1, 4 * mm),
        table,
        Spacer(1, 6 * mm),
        _qr(data.verify_url),
        Paragraph(f'Check this certificate: <link href="{link}">{link}</link>', body),
        Spacer(1, 8 * mm),
        Paragraph(FOOTER, footer),
    ]
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        pageCompression=0,
        title=f"Authorship certificate {data.cert_id}",
        subject=f"SHA-256 {data.content_hash.hex()}",
        creator="Bridge provenance",
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    document.build(story)
    return buffer.getvalue()


_CERTIFICATE = text(
    "SELECT r.cert_id, r.content_hash, r.signature, r.key_id, r.status, r.tsa_time, r.tsa_serial, v.id AS version_id,"
    " v.version_no, v.title, v.registered_at, v.owner_handle, p.owner_id"
    " FROM provenance_records r JOIN proposal_versions v ON v.id = r.version_id"
    " JOIN proposals p ON p.id = v.proposal_id WHERE r.cert_id = :cert_id AND p.owner_id = :user"
)
_ATTACHMENTS = text(
    "SELECT sha256 FROM proposal_attachments WHERE version_id = :version AND sha256 IS NOT NULL ORDER BY sha256"
)
_PROFILE = text("SELECT handle, verification_level FROM developer_profiles WHERE user_id = :user")
_LEGAL_NAME = text(
    "SELECT verified_legal_name FROM kyc_reviews WHERE user_id = :user AND status = 'approved'"
    " AND verified_legal_name IS NOT NULL ORDER BY decided_at DESC NULLS LAST LIMIT 1"
)
_D2 = {DevVerification.D2, DevVerification.D3}


async def load_certificate(
    session: AsyncSession, *, cert_id: str, user_id: UUID, public_base_url: str
) -> CertificateData | None:
    """The certificate of one of ``user_id``'s registered versions, or None (not theirs, or no such cert)."""
    row = (await session.execute(_CERTIFICATE, {"cert_id": cert_id, "user": user_id})).one_or_none()
    if row is None:
        return None
    hashes = (await session.execute(_ATTACHMENTS, {"version": row.version_id})).scalars().all()
    profile = (await session.execute(_PROFILE, {"user": user_id})).one_or_none()
    legal = None
    if profile is not None and profile.verification_level in _D2:
        legal = (await session.execute(_LEGAL_NAME, {"user": user_id})).scalar_one_or_none()
    handle = profile.handle if profile is not None else row.owner_handle
    return CertificateData(
        cert_id=row.cert_id,
        version_id=row.version_id,
        title=row.title,
        version_no=row.version_no,
        owner_name=legal or handle,
        owner_is_legal_name=legal is not None,
        registered_at=row.registered_at,
        status=ProvenanceStatus(row.status),
        content_hash=bytes(row.content_hash),
        signature=None if row.signature is None else bytes(row.signature),
        key_id=row.key_id,
        tsa_time=row.tsa_time,
        tsa_serial=row.tsa_serial,
        verify_url=verify_url(public_base_url, row.cert_id),
        attachment_hashes=tuple(bytes(h) for h in hashes),
    )
