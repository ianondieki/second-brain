"""REQ-PROV-02 / AC-IP-1: the authorship certificate PDF carries the cert id, owner (legal name only when D2), UTC and
EAT times, hash, signature and key id, TSA serial or "Timestamp pending", attachment hashes, the verify link and QR,
and exactly the fixed footer of docs/spec/06 6.4 item 2."""

from __future__ import annotations

import re
import zlib
from datetime import UTC, datetime
from typing import Any

from bridge.models.enums import ProvenanceStatus
from bridge.provenance.certificate import FOOTER, CertificateData, eat_text, render_pdf, utc_text, verify_url

SPEC_FOOTER = (
    "This certificate is evidence of what was submitted and when. It is not a patent, copyright registration or "
    "guarantee against independent development or misuse."
)
REGISTERED = datetime(2026, 9, 28, 6, 15, 30, tzinfo=UTC)
STAMPED = datetime(2026, 9, 28, 6, 15, 42, tzinfo=UTC)


def data(**overrides: Any) -> CertificateData:
    values: dict[str, Any] = {
        "cert_id": "BRX7K2M9Q4TZ8W3D",
        "title": "Cold-chain alerts",
        "version_no": 1,
        "owner_name": "dev-handle",
        "owner_is_legal_name": False,
        "registered_at": REGISTERED,
        "status": ProvenanceStatus.TIMESTAMPED,
        "content_hash": bytes(range(32)),
        "signature": bytes(64),
        "key_id": "ed25519:0123456789abcdef",
        "tsa_time": STAMPED,
        "tsa_serial": "0x01A2",
        "verify_url": "https://bridge.example/verify/BRX7K2M9Q4TZ8W3D",
        "attachment_hashes": (bytes([1]) * 32, bytes([2]) * 32),
    }
    values.update(overrides)
    return CertificateData(**values)


def pdf_text(pdf: bytes) -> str:
    """The text drawn on the page (reportlab writes it as literal strings shown with Tj), whitespace-normalised."""
    assert pdf.startswith(b"%PDF-")
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S)
    content = b"".join(s if b"Tj" in s else _maybe_inflate(s) for s in streams)
    parts = re.findall(rb"\(((?:\\.|[^\\)])*)\)\s*Tj", content)
    text = " ".join(re.sub(rb"\\(.)", rb"\1", p).decode("latin-1") for p in parts)
    return re.sub(r"\s+", " ", text)


def _maybe_inflate(stream: bytes) -> bytes:
    try:
        return zlib.decompress(stream)
    except zlib.error:
        return stream


def test_the_footer_is_exactly_the_spec_text() -> None:
    assert FOOTER == SPEC_FOOTER
    assert SPEC_FOOTER in pdf_text(render_pdf(data()))


def test_the_certificate_shows_every_required_fact() -> None:
    pdf = render_pdf(data())
    text = pdf_text(pdf)
    for expected in (
        "BRX7K2M9Q4TZ8W3D",
        "Cold-chain alerts",
        "dev-handle (handle), 100%",
        "2026-09-28 06:15:42 UTC",
        "2026-09-28 09:15:42 EAT (UTC+3)",
        bytes(range(32)).hex(),
        "ed25519:0123456789abcdef",
        "0x01A2",
        (bytes([1]) * 32).hex(),
        (bytes([2]) * 32).hex(),
        "Timestamped",
        "https://bridge.example/verify/BRX7K2M9Q4TZ8W3D",
    ):
        assert expected in text, expected
    assert b"/URI (https://bridge.example/verify/BRX7K2M9Q4TZ8W3D)" in pdf
    assert b"Authorship certificate BRX7K2M9Q4TZ8W3D" in pdf  # document title metadata


def test_pending_records_say_so() -> None:
    text = pdf_text(
        render_pdf(
            data(status=ProvenanceStatus.HASHED, tsa_time=None, tsa_serial=None, signature=None, key_id=None,
                 attachment_hashes=())  # fmt: skip
        )
    )
    assert "Timestamp pending" in text
    assert "Signature pending" in text
    assert "Registered (timestamp pending)" in text
    assert "2026-09-28 06:15:30 UTC" in text
    assert "No attachments" in text


def test_a_d2_owner_is_named_and_owner_text_is_escaped() -> None:
    text = pdf_text(render_pdf(data(owner_name="Wanjiru <b>Kamau</b> & Co", owner_is_legal_name=True)))
    # The markup is drawn as text, not applied (reportlab draws "<" and ">" as their own runs).
    assert "Wanjiru<b>Kamau</b>&Co(verifiedlegalname)" in text.replace(" ", "")
    assert "(handle)" not in text


def test_time_helpers() -> None:
    assert utc_text(STAMPED) == "2026-09-28 06:15:42 UTC"
    assert eat_text(STAMPED) == "2026-09-28 09:15:42 EAT (UTC+3)"
    assert verify_url("https://bridge.example/", "ABC12345") == "https://bridge.example/verify/ABC12345"
