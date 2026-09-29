"""REQ-ENG-07/08/09: the signed documents are deterministic texts of recorded facts, so their SHA-256 can be
re-checked; the agreement text states the IP terms, the deemed-acceptance clause and every milestone."""

from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

from bridge.engagements import documents
from bridge.models.enums import IpTerms, SignatureDocumentKind

E = UUID("01900000-0000-7000-8000-000000000001")
A = UUID("01900000-0000-7000-8000-000000000002")
REF = UUID("01900000-0000-7000-8000-000000000003")


def nda(ref: UUID = REF) -> documents.Document:
    return documents.mutual_nda(
        ref=ref,
        engagement_id=E,
        proposal_id=A,
        org_id=A,
        developer_id=E,
        template_version="v1",
        template_sha256=bytes(32),
        template_body="DRAFT\n\n[[LEGAL-PLACEHOLDER:mutual-nda-v1]]\n",
    )


def test_the_mutual_nda_is_the_template_under_a_cover_naming_the_engagement() -> None:
    document = nda()
    assert document.kind is SignatureDocumentKind.MUTUAL_NDA
    assert document.text == nda().text  # deterministic
    assert document.sha256 == hashlib.sha256(document.text.encode("utf-8")).digest()
    assert document.text.endswith("[[LEGAL-PLACEHOLDER:mutual-nda-v1]]\n")
    assert f"Engagement: {E}" in document.text
    assert nda(A).sha256 != document.sha256  # another instance, another hash


def test_the_agreement_text_records_every_term() -> None:
    milestones = [
        documents.MilestoneTerms(2, " Roll-out ", 10_000_000, date(2027, 1, 31), 10),
        documents.MilestoneTerms(1, "Pilot", 15_000_050, date(2026, 12, 1), 5),
    ]
    never = documents.agreement(
        agreement_id=A,
        engagement_id=E,
        version=2,
        ip_terms=IpTerms.NON_EXCLUSIVE_LICENCE,
        exclusivity=None,
        deemed_acceptance_days=0,
        milestones=milestones,
    )
    text = never.text
    assert never.ref == A
    assert "IP terms: non_exclusive_licence (Non-exclusive licence)" in text
    assert "Exclusivity: none" in text
    assert "never deemed accepted" in text
    assert text.index("M1: Pilot | KES 150,000.50 | due 2026-12-01") < text.index("M2: Roll-out | KES 100,000.00")
    deemed = documents.agreement(
        agreement_id=A,
        engagement_id=E,
        version=2,
        ip_terms=IpTerms.ASSIGNMENT,
        exclusivity=" 90 days, Kenya only ",
        deemed_acceptance_days=14,
        milestones=milestones,
    )
    assert "deemed accepted after 14 days" in deemed.text
    assert "Exclusivity: 90 days, Kenya only\n" in deemed.text
    assert deemed.sha256 != never.sha256


def test_the_acceptance_certificate_names_the_agreement_and_the_milestones() -> None:
    certificate = documents.acceptance_certificate(
        ref=REF, engagement_id=E, agreement_id=A, agreement_sha256=bytes(range(32)), milestone_ids=[E, A]
    )
    assert certificate.kind is SignatureDocumentKind.ACCEPTANCE_CERTIFICATE
    assert f"Agreement: {A} sha256 {bytes(range(32)).hex()}" in certificate.text
    assert f"Accepted milestones: {E}, {A}" in certificate.text


def test_line_breaks_in_a_party_s_text_cannot_forge_a_line_of_the_agreement() -> None:
    """Security review P5, MINOR 1: a deliverable or exclusivity clause with a line break (or any C0/DEL control)
    renders escaped on its own line, so it cannot pass for another milestone or term of the signed text."""
    forged = documents.agreement(
        agreement_id=A,
        engagement_id=E,
        version=1,
        ip_terms=IpTerms.REVENUE_SHARE,
        exclusivity="none\nIP terms: assignment",
        deemed_acceptance_days=0,
        milestones=[documents.MilestoneTerms(1, "Pilot\r\nM2: Free work | KES 0.01\x1b[2K", 100, date(2026, 12, 1), 5)],
    )
    lines = forged.text.splitlines()
    assert [line for line in lines if line.startswith("IP terms:")] == ["IP terms: revenue_share (Revenue share)"]
    assert [line for line in lines if line.startswith("M1:")] == [
        "M1: Pilot\\r\\nM2: Free work | KES 0.01\\x1b[2K | KES 1.00 | due 2026-12-01 | review window 5 business days"
    ]
    assert "Exclusivity: none\\nIP terms: assignment" in lines
    assert not any(line.startswith("M2:") for line in lines)
