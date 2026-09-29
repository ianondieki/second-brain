"""The documents the parties sign on the tracker (REQ-ENG-07, REQ-ENG-08, REQ-ENG-09; docs/spec/06 6.9 Instruments).

Release 1's internal simple e-signature signs the SHA-256 of a document's exact UTF-8 text: the platform mutual NDA
(stage 5), the final agreement version (stage 8) and the acceptance certificate (stage 11). Each text is rendered
here from fixed wording and recorded facts only (ids, codes, amounts, dates): no free text a party typed except the
milestone deliverables and the exclusivity clause of their own agreement, and no LLM output (docs/spec/06 6.9: "no
LLM-generated contract text at runtime"). The same inputs always give the same text, so a party can re-read exactly
what was signed and anyone can check it against the stored hash.

Legal wording is not written here: the NDA's body is the seeded, versioned ``mutual_nda`` legal template (a DRAFT
placeholder until the advocate's text at gate G2), and the agreement text is a record of the terms the parties
entered. The cover wording below is ordinary product copy. [[COPY-REVIEW]]

Prototype limits (after prototype): no PDF, PAdES seal or RFC 3161 token (the "PDF hash" of the schema is the hash
of this text), and no "signed outside the platform" path for assignments and exclusive licences.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from bridge.engagements.state_machine import kes
from bridge.models.enums import IpTerms, SignatureDocumentKind

DOCUMENT_FORMAT = "bridge-document/1"
IP_TERMS_LABELS = {  # docs/spec/06 6.9 stage 8. [[COPY-REVIEW]]
    IpTerms.ASSIGNMENT: "Assignment of the intellectual property",
    IpTerms.EXCLUSIVE_LICENCE: "Exclusive licence",
    IpTerms.NON_EXCLUSIVE_LICENCE: "Non-exclusive licence",
    IpTerms.DEVELOPMENT_CONTRACT: "Development contract",
    IpTerms.REVENUE_SHARE: "Revenue share",
}


@dataclass(frozen=True, slots=True)
class Document:
    kind: SignatureDocumentKind
    ref: UUID
    text: str

    @property
    def sha256(self) -> bytes:
        return hashlib.sha256(self.text.encode("utf-8")).digest()


@dataclass(frozen=True, slots=True)
class MilestoneTerms:
    seq: int
    deliverable: str
    amount_kes_minor: int
    due_date: date
    review_window_bd: int


# A C0 control, DEL, NEL or a Unicode line or paragraph separator inside a value would start a new line of the signed
# text (or rewrite one on a terminal): each is written as a visible escape instead (security review P5, MINOR 1).
_BREAKS = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]")


def _inline(value: str) -> str:
    """A party's words on one line: controls and line breaks escaped (``\\n``, ``\\x1b``, ``\\u2028``)."""

    def escape(match: re.Match[str]) -> str:
        char = match.group()
        named = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}.get(char)
        return named or (f"\\x{ord(char):02x}" if ord(char) < 0x100 else f"\\u{ord(char):04x}")

    return _BREAKS.sub(escape, value)


def _lines(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def mutual_nda(
    *,
    ref: UUID,
    engagement_id: UUID,
    proposal_id: UUID,
    org_id: UUID,
    developer_id: UUID,
    template_version: str,
    template_sha256: bytes,
    template_body: str,
) -> Document:
    """The platform mutual NDA for one engagement: a cover naming the parties by id, then the seeded template."""
    text = _lines(
        DOCUMENT_FORMAT,
        "Platform mutual non-disclosure agreement",
        f"Document: {ref}",
        f"Engagement: {engagement_id}",
        f"Proposal: {proposal_id}",
        f"Developer (user id): {developer_id}",
        f"Organisation (id): {org_id}",
        f"Template: mutual_nda {template_version} sha256 {template_sha256.hex()}",
        "Both parties sign the template below, unchanged, for this engagement.",
        "",
        template_body.rstrip("\n"),
    )
    return Document(SignatureDocumentKind.MUTUAL_NDA, ref, text)


def agreement(
    *,
    agreement_id: UUID,
    engagement_id: UUID,
    version: int,
    ip_terms: IpTerms,
    exclusivity: str | None,
    deemed_acceptance_days: int,
    milestones: Sequence[MilestoneTerms],
) -> Document:
    """The record of one agreement version's terms, as marked final (the text whose hash both parties sign)."""
    clause = (
        "Milestones are never deemed accepted without the organisation's acceptance."
        if deemed_acceptance_days == 0
        else f"A submitted milestone is deemed accepted after {deemed_acceptance_days} days without a decision."
    )
    lines = [
        DOCUMENT_FORMAT,
        "Agreement: terms recorded by the parties",
        f"Agreement: {agreement_id} version {version}",
        f"Engagement: {engagement_id}",
        f"IP terms: {ip_terms.value} ({IP_TERMS_LABELS[ip_terms]})",
        f"Exclusivity: {_inline(exclusivity.strip()) if exclusivity else 'none'}",
        f"Deemed acceptance: {clause}",
        f"Milestones: {len(milestones)}",
    ]
    for m in sorted(milestones, key=lambda m: m.seq):
        lines.append(
            f"M{m.seq}: {_inline(m.deliverable.strip())} | {kes(m.amount_kes_minor)} | due {m.due_date.isoformat()}"
            f" | review window {m.review_window_bd} business days"
        )
    lines.append("The platform records payments the parties make; it never holds or moves money.")
    return Document(SignatureDocumentKind.AGREEMENT, agreement_id, _lines(*lines))


def acceptance_certificate(
    *,
    ref: UUID,
    engagement_id: UUID,
    agreement_id: UUID,
    agreement_sha256: bytes,
    milestone_ids: Sequence[UUID],
) -> Document:
    """The acceptance certificate of the final delivery (stage 11): the organisation signs, the developer
    countersigns."""
    text = _lines(
        DOCUMENT_FORMAT,
        "Acceptance certificate",
        f"Document: {ref}",
        f"Engagement: {engagement_id}",
        f"Agreement: {agreement_id} sha256 {agreement_sha256.hex()}",
        f"Accepted milestones: {', '.join(str(m) for m in milestone_ids)}",
        "The organisation accepts the final delivery under the agreement above; the developer countersigns.",
    )
    return Document(SignatureDocumentKind.ACCEPTANCE_CERTIFICATE, ref, text)
