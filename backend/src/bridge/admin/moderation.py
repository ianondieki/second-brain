"""The moderation queue (REQ-MOD-01, REQ-PROP-02; docs/spec/06 6.12), the prototype's minimal staff part.

Staff admin or moderator list the unresolved cases (open, held, escalated) with a Tier-1 preview of their proposal or
problem, and decide one: approve (the subject becomes ``clear``; a problem ``published``) or reject (``rejected``).
The subject's state changes only through ``app_moderate_proposal`` / ``app_moderate_problem`` (SECURITY DEFINER:
staff only, never on their own content); the case records who decided and when, and the decision is audited on the
staff member's chain. Approving a held proposal writes its ``proposal_published`` signal, which publishing withheld.

Vulnerability content is never made public (REQ-PROP-02): while the subject's current Tier-1 text screens as
``security_vulnerability``, ``approve`` answers 409 ``cannot_approve_vulnerability`` and only ``reject`` is possible.
A false positive is released by its author, who publishes a corrected version; that version is screened again, and
once it no longer screens as a vulnerability a moderator may approve the case (whose reasons keep the history).

A decision is about what the moderator reviewed: a proposal case carries the proposal's current version
(``subject_version_id``, the version the preview shows) and the decision must send it back. When the author has
published another version in the meantime (it joins the open case), the decision answers 409 ``case_changed`` and
changes nothing; the version is compared again after the subject's row is locked by the moderation function, so a
version published concurrently cannot slip through. Problems have no versions: their cases carry null.

The queue (P15) shows what a moderator needs to decide: the subject's current Tier-1 text field by field (never Tier
2), the fields the pre-screen flagged, and the decisions the decision route accepts from this moderator now
(``actions``) with the code it answers otherwise (``blocked``: ``already_decided``, ``unsupported_subject`` for a case
decided from its own queue, ``subject_gone``, ``own_content``, ``cannot_approve_vulnerability``). Plain code works these
out as the decision does; the database still decides (``app_moderate_*``). Unresolved cases come oldest first; decided
ones newest decision first, with who decided. At most 200 either way; one case is read by its id wherever it falls.
Claims are read in their own queue (``bridge.admin.claims``); research approval is ``bridge.admin.research``.

Message reports (REQ-ENG-11, D-57 (4); ``subject_type = 'message'``, filed by a party through
``app_report_message``): the lists show "Reported message" with the reason codes and never the text; the case read by
its id carries the one reported message (its engagement, sender side, text and time) through
``app_reported_message``, the only way staff read a message, and each such read writes an audit event (ids only).
Staff never read the rest of the thread. A report is decided ``dismiss`` (nothing wrong: the case ends ``approved``)
or ``uphold`` (the message broke the rules: ``rejected``), with an optional staff note kept in the decision's audit
details; the message itself never changes (a staff redaction is D-54's later function). The reporter never decides
their own report (``own_content``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.errors import ApiError, not_found
from bridge.matching.tasks import defer_on_new
from bridge.models.enums import AuditActor, EngagementParty, ModerationCaseStatus, ModerationSource, ModerationState
from bridge.problems.service import org_ref
from bridge.proposals.prescreen import SECURITY_VULNERABILITY, RulesPreScreen, ScreenInput
from bridge.proposals.schemas import OrgRef
from bridge.proposals.service import signal

UNRESOLVED: Final = ("open", "held", "escalated")
Decision = Literal["approve", "reject", "dismiss", "uphold"]  # dismiss / uphold: message reports only
MESSAGE: Final = "message"
MESSAGE_TITLE: Final = "Reported message"  # [[COPY-REVIEW]] the queue's title of a message report
# A message report's outcome as the case's status: dismissed, the message stands (approved); upheld, it broke the rules.
MESSAGE_OUTCOMES: Final[Mapping[str, ModerationCaseStatus]] = {
    "dismiss": ModerationCaseStatus.APPROVED,
    "uphold": ModerationCaseStatus.REJECTED,
}
_LINES: Final = r"^[^\x00-\x08\x0b-\x1f\x7f]*$"  # line feeds and tabs only (as the tracker's notes)
# Why a case cannot be decided: the decision route's refusal code (subject_gone: the subject no longer exists).
Blocked = Literal[
    "already_decided", "unsupported_subject", "subject_gone", "own_content", "cannot_approve_vulnerability"
]
# The Tier-1 fields of each subject this queue decides, in reading order: what the queue shows and what a decision
# screens again for a vulnerability.
TIER1_FIELDS: Final[Mapping[str, tuple[str, ...]]] = {
    "proposal": ("title", "problem_statement", "impact_claims", "summary"),
    "problem": ("title", "statement", "affected_group"),  # a Brief's affected group is public text too (REQ-DIR-05)
}


class CasePreview(BaseModel):
    """Tier-1 text of the subject (never Tier 2)."""

    title: str | None
    text: str | None


class CaseField(BaseModel):
    name: str = Field(
        description="A Tier-1 field: title, problem_statement, impact_claims, summary, statement, affected_group"
    )
    text: str


class ReportedMessageOut(BaseModel):
    """The one message a report shared with staff (``app_reported_message``): never the rest of its thread."""

    message_id: UUID
    engagement_id: UUID
    sender_party: EngagementParty
    body: str = Field(description="The message's plain text as the party typed it: render it as text")
    created_at: datetime


class StaffRef(BaseModel):
    id: UUID
    display_name: str


class CaseOut(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    reasons: list[str]
    source: ModerationSource
    status: ModerationCaseStatus
    created_at: datetime
    subject_state: ModerationState | None
    subject_version_id: UUID | None = Field(description="The proposal version the preview shows; null for problems")
    preview: CasePreview
    fields: list[CaseField] = Field(description="The subject's current Tier-1 text, field by field (never Tier 2)")
    flagged_fields: list[str] = Field(description="The Tier-1 fields the pre-screen flagged when it filed the case")
    actions: list[Decision] = Field(description="The decisions the decision route accepts from you now")
    blocked: Blocked | None = Field(description="Why a decision is refused (the route's code); null when both are open")
    decided_at: datetime | None
    decided_by: StaffRef | None
    brief_org: OrgRef | None = Field(
        default=None,
        description="The organisation that posted the problem as a Problem Brief (REQ-DIR-05: 'Brief by <org>');"
        " null for any other subject, or when the organisation is not in the directory",
    )
    message: ReportedMessageOut | None = Field(
        default=None,
        description="A message report's message, on the case read by its id only (each read is audited); null in"
        " the lists and for every other subject",
    )


class CaseList(BaseModel):
    items: list[CaseOut]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision
    subject_version_id: UUID | None = Field(description="The case's subject_version_id as reviewed (required)")
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=2000,
        pattern=_LINES,
        description="A staff note on the decision, kept in its audit details (never shown to the parties)",
    )


class DecisionOut(BaseModel):
    id: UUID
    status: ModerationCaseStatus
    subject_state: ModerationState | None = Field(description="The subject's state now; null for a message report")


_CASES_SELECT: Final = (
    "SELECT m.id, m.subject_type, m.subject_id, m.reasons, m.source, m.status, m.created_at, m.classifier,"
    " m.decided_at, m.decided_by, d.display_name AS decider_name,"
    # A message is never deleted (revision 0008: append-only), so a message report's subject is always there.
    " (p.id IS NOT NULL OR pr.id IS NOT NULL OR m.subject_type = 'message') AS found,"
    " coalesce(p.moderation_state, pr.moderation_state) AS subject_state, p.current_version_id AS subject_version_id,"
    " coalesce(p.owner_id = :staff, pr.created_by = :staff,"
    " CASE WHEN m.subject_type = 'message' THEN m.reporter_id = :staff END, false) AS own,"
    " coalesce(p.title, pr.title) AS title, p.problem_statement, p.impact_claims, p.summary, pr.statement,"
    " pr.affected_group, bo.id AS brief_org_id, bo.slug::text AS brief_org_slug, bo.legal_name AS brief_org_name"
    " FROM moderation_cases m"
    " LEFT JOIN proposals p ON m.subject_type = 'proposal' AND p.id = m.subject_id"
    " LEFT JOIN problems pr ON m.subject_type = 'problem' AND pr.id = m.subject_id"
    " LEFT JOIN organizations bo ON pr.source = 'org_brief' AND bo.id = pr.org_id"
    " LEFT JOIN users d ON d.id = m.decided_by"
)
_OPEN_CASES = text(
    _CASES_SELECT + " WHERE m.status IN ('open', 'held', 'escalated') ORDER BY m.created_at, m.id LIMIT 200"
)
_DECIDED_CASES = text(
    _CASES_SELECT + " WHERE m.status NOT IN ('open', 'held', 'escalated')"
    " ORDER BY m.decided_at DESC NULLS LAST, m.created_at DESC, m.id DESC LIMIT 200"
)
_ONE_CASE = text(_CASES_SELECT + " WHERE m.id = :id")


def decision_options(
    *, unresolved: bool, subject_type: str, found: bool, own: bool, vulnerable: bool
) -> tuple[list[Decision], Blocked | None]:
    """The decisions the decision route accepts for a case, and the code it answers when it refuses them."""
    if not unresolved:
        return [], "already_decided"
    if subject_type == MESSAGE:  # a report: the reporter never decides it
        return ([], "own_content") if own else (["dismiss", "uphold"], None)
    if subject_type not in TIER1_FIELDS:
        return [], "unsupported_subject"
    if not found:
        return [], "subject_gone"
    if own:  # app_moderate_proposal / app_moderate_problem never let staff decide on their own content
        return [], "own_content"
    if vulnerable:  # REQ-PROP-02: vulnerability content is never made public
        return ["reject"], "cannot_approve_vulnerability"
    return ["approve", "reject"], None


def flagged_fields(classifier: Any) -> list[str]:
    """The Tier-1 field names in the pre-screen's output (one screen's ``fields``, or each of ``merge``'s
    ``screens``), in order and once each; anything else is ignored."""
    if not isinstance(classifier, Mapping):
        return []
    screens = classifier.get("screens")
    names: dict[str, None] = {}
    for screen in screens if isinstance(screens, list) else [classifier]:
        found = screen.get("fields") if isinstance(screen, Mapping) else None
        for name in found if isinstance(found, list) else []:
            if isinstance(name, str) and name:
                names.setdefault(name, None)
    return list(names)


async def screens_as_vulnerability(fields: Mapping[str, str]) -> bool:
    """Whether Tier-1 text screens as a security vulnerability (``RulesPreScreen``, as when it was published)."""
    return SECURITY_VULNERABILITY in (await RulesPreScreen().screen(ScreenInput(fields))).reasons


async def _case_out(row: Any, *, unresolved: bool) -> CaseOut:
    names = TIER1_FIELDS.get(row.subject_type, ())
    values = row._asdict()
    fields = {name: values[name] for name in names if values.get(name)}
    decidable = unresolved and row.found and not row.own and row.subject_type in TIER1_FIELDS
    actions, blocked = decision_options(
        unresolved=unresolved,
        subject_type=row.subject_type,
        found=row.found,
        own=row.own,
        vulnerable=decidable and await screens_as_vulnerability(fields),
    )
    return CaseOut(
        id=row.id,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        reasons=list(row.reasons),
        source=row.source,
        status=row.status,
        created_at=row.created_at,
        subject_state=row.subject_state,
        subject_version_id=row.subject_version_id,
        preview=CasePreview(title=MESSAGE_TITLE, text=None)
        if row.subject_type == MESSAGE
        else CasePreview(title=row.title, text=row.summary or row.statement),
        fields=[CaseField(name=name, text=value) for name, value in fields.items()],
        flagged_fields=flagged_fields(row.classifier),
        actions=actions,
        blocked=blocked,
        decided_at=row.decided_at,
        decided_by=None if row.decided_by is None else StaffRef(id=row.decided_by, display_name=row.decider_name),
        brief_org=org_ref(row.brief_org_id, row.brief_org_slug, row.brief_org_name),
    )


async def list_cases(db: AsyncSession, *, unresolved: bool, staff_id: UUID) -> CaseList:
    """The queue as ``staff_id`` sees it: unresolved cases oldest first, or decided ones newest decision first."""
    rows = (await db.execute(_OPEN_CASES if unresolved else _DECIDED_CASES, {"staff": staff_id})).all()
    return CaseList(items=[await _case_out(row, unresolved=unresolved) for row in rows])


async def get_case(db: AsyncSession, *, case_id: UUID, staff_id: UUID) -> CaseOut | None:
    """One case as ``staff_id`` sees it in the queue, open or decided, wherever it falls in the lists; None when
    there is no such case (the case page, P16-E1: a queue longer than 200 no longer hides it). A message report
    carries its message, and the read is audited (committed)."""
    row = (await db.execute(_ONE_CASE, {"id": case_id, "staff": staff_id})).one_or_none()
    if row is None:
        return None
    case = await _case_out(row, unresolved=row.status in UNRESOLVED)
    if row.subject_type == MESSAGE:
        case.message = await reported_message(db, case_id=case_id, staff_id=staff_id)
    return case


_REPORTED_MESSAGE = text(
    "SELECT message_id, engagement_id, sender_party, body, created_at FROM app_reported_message(:case)"
)


async def reported_message(db: AsyncSession, *, case_id: UUID, staff_id: UUID) -> ReportedMessageOut | None:
    """The message of a message report, read through ``app_reported_message`` (staff admin or moderator), with an
    audit event on the staff member's chain for every read (ids only, never the text). Committed."""
    row = (await db.execute(_REPORTED_MESSAGE, {"case": case_id})).one_or_none()
    if row is None:
        return None
    await audit(
        db,
        "moderation.reported_message_read",
        actor_user_id=staff_id,
        actor_kind=AuditActor.STAFF,
        subject_type="moderation_case",
        subject_id=case_id,
        payload={"message_id": str(row.message_id), "engagement_id": str(row.engagement_id)},
    )
    await db.commit()
    return ReportedMessageOut(
        message_id=row.message_id,
        engagement_id=row.engagement_id,
        sender_party=row.sender_party,
        body=row.body,
        created_at=row.created_at,
    )


_CASE = text("SELECT id, subject_type, subject_id, status, reporter_id FROM moderation_cases WHERE id = :id FOR UPDATE")
_PROPOSAL = text("SELECT owner_id, status, moderation_state, current_version_id FROM proposals WHERE id = :id")
_CURRENT_VERSION = text("SELECT current_version_id FROM proposals WHERE id = :id")
_MODERATE_PROPOSAL = text("SELECT app_moderate_proposal(:id, CAST(:state AS moderation_state))")
_MODERATE_PROBLEM = text(
    "SELECT app_moderate_problem(:id, CAST(:state AS moderation_state), CAST(:status AS problem_status))"
)
_CLOSE = text(
    "UPDATE moderation_cases SET status = CAST(:status AS moderation_case_status), decided_by = :staff,"
    " decided_at = now(), updated_at = now() WHERE id = :id"
)


# The TIER1_FIELDS of each subject (a unit test keeps the two in step).
_CURRENT_TEXT = {
    "proposal": text("SELECT title, problem_statement, impact_claims, summary FROM proposals WHERE id = :id"),
    "problem": text("SELECT title, statement, affected_group FROM problems WHERE id = :id"),
}


def _refusal(exc: DBAPIError) -> ApiError | None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "P0002":  # no_data_found: the moderator's own content (or a subject removed while deciding)
        return ApiError(403, "own_content", "You cannot moderate your own content or content that no longer exists.")
    if sqlstate == "42501":  # the database's staff check
        return not_found()
    return None


def _case_changed() -> ApiError:
    return ApiError(409, "case_changed", "The author published a new version. Review the case again.")


async def _subject_version(db: AsyncSession, subject_type: str, subject_id: UUID) -> UUID | None:
    if subject_type != "proposal":
        return None
    version: UUID | None = (await db.execute(_CURRENT_VERSION, {"id": subject_id})).scalar_one_or_none()
    return version


async def _decide_message(
    db: AsyncSession, *, staff_id: UUID, case: Any, decision: Decision, note: str | None
) -> DecisionOut:
    """Dismiss or uphold a message report: the case closes (the message never changes) and the decision is audited
    with the staff note in its details."""
    if decision not in MESSAGE_OUTCOMES:
        raise ApiError(422, "invalid_decision", "Dismiss or uphold a message report.")
    if case.reporter_id == staff_id:
        raise ApiError(403, "own_content", "You cannot decide your own report.")
    outcome = MESSAGE_OUTCOMES[decision]
    await db.execute(_CLOSE, {"status": outcome.value, "staff": staff_id, "id": case.id})
    await audit(
        db,
        "moderation.case_decided",
        actor_user_id=staff_id,
        actor_kind=AuditActor.STAFF,
        subject_type="moderation_case",
        subject_id=case.id,
        payload={"subject_type": MESSAGE, "subject_id": str(case.subject_id), "decision": decision},
        details={"note": note} if note else None,
    )
    await db.commit()
    return DecisionOut(id=case.id, status=outcome, subject_state=None)


async def decide(
    db: AsyncSession,
    *,
    staff_id: UUID,
    case_id: UUID,
    decision: Decision,
    subject_version_id: UUID | None,
    note: str | None = None,
) -> DecisionOut:
    case = (await db.execute(_CASE, {"id": case_id})).one_or_none()
    if case is None:
        raise not_found("No such case.")
    if case.status not in UNRESOLVED:
        raise ApiError(409, "already_decided", "This case was already decided.")
    if case.subject_type == MESSAGE:
        return await _decide_message(db, staff_id=staff_id, case=case, decision=decision, note=note)
    if decision not in ("approve", "reject"):
        raise ApiError(422, "invalid_decision", "Approve or reject this case.")
    if case.subject_type not in _CURRENT_TEXT:
        raise ApiError(409, "unsupported_subject", "Decide this case from its own queue.")
    current = (await db.execute(_CURRENT_TEXT[case.subject_type], {"id": case.subject_id})).one_or_none()
    if current is None:
        raise ApiError(409, "subject_gone", "The proposal or problem of this case no longer exists.")
    if await _subject_version(db, case.subject_type, case.subject_id) != subject_version_id:
        raise _case_changed()
    approve = decision == "approve"
    # Screened again now: the current Tier-1 text, not the one the case was filed about.
    if approve and await screens_as_vulnerability({name: value for name, value in current._asdict().items() if value}):
        raise ApiError(
            409,
            "cannot_approve_vulnerability",
            "Vulnerability reports are never made public: reject this case. The author can publish a corrected"
            " version, which is screened again.",
        )
    state = ModerationState.CLEAR if approve else ModerationState.REJECTED
    proposal: Any = None
    try:
        if case.subject_type == "proposal":
            proposal = (await db.execute(_PROPOSAL, {"id": case.subject_id})).one_or_none()
            await db.execute(_MODERATE_PROPOSAL, {"id": case.subject_id, "state": state.value})
        else:
            status = "published" if approve else "rejected"
            await db.execute(_MODERATE_PROBLEM, {"id": case.subject_id, "state": state.value, "status": status})
    except DBAPIError as exc:
        refusal = _refusal(exc)
        if refusal is None:
            raise
        await db.rollback()
        raise refusal from None
    # The moderation function's UPDATE holds the subject's row lock until COMMIT: compare again, so a version
    # published while this decision ran is not approved or rejected unseen.
    if await _subject_version(db, case.subject_type, case.subject_id) != subject_version_id:
        await db.rollback()
        raise _case_changed()
    outcome = ModerationCaseStatus.APPROVED if approve else ModerationCaseStatus.REJECTED
    await db.execute(_CLOSE, {"status": outcome.value, "staff": staff_id, "id": case_id})
    if (
        approve
        and proposal is not None
        and proposal.status == "published"
        and proposal.moderation_state != ModerationState.CLEAR
    ):
        await signal(db, proposal_id=case.subject_id, owner_id=proposal.owner_id)
        await defer_on_new(db, case.subject_id)  # visible now: the on_new scouts' run (REQ-SCOUT-02)
    await audit(
        db,
        "moderation.case_decided",
        actor_user_id=staff_id,
        actor_kind=AuditActor.STAFF,
        subject_type="moderation_case",
        subject_id=case_id,
        payload={"subject_type": case.subject_type, "subject_id": str(case.subject_id), "decision": decision},
        details={"note": note} if note else None,
    )
    await db.commit()
    return DecisionOut(id=case_id, status=outcome, subject_state=state)
