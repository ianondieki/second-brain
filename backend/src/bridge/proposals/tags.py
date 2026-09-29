"""'Pitch to company': tags (REQ-PROP-03, REQ-REPO-03, REQ-BIL-02, REQ-DIR-04 held tags; docs/spec/06 6.2, 6.3).

A developer at D1 or above (the routes' ``D1Developer``, AC-IP-5) pitches one of their published, clear proposals to
one or more listed organisations at once. Plain code decides, in one transaction, or nothing is created:

1. the proposal is the caller's (404 otherwise) and published and clear (409 ``proposal_not_public``);
2. every organisation is listed in the directory (404 otherwise);
3. no conflict (409 ``tag_conflict`` with a reason per organisation): the caller is not a member of it; no open tag
   or open engagement of theirs with it already (one open engagement or held tag per developer and organisation,
   AC-PROP-7; also enforced by ``uq_tags_open_developer_org``); this proposal was not pitched to it before (one
   engagement per proposal and organisation); no decline of theirs by it in the last 30 days (on the shared clock,
   ``app_clock_now()``); a verified organisation is not suspended;
4. the plan's ``tags_per_proposal`` has room for the whole batch (402 with the upgrade path, AC-PROP-2); a tag counts
   unless it was withdrawn or released before it reached the organisation;
5. each tag is inserted by the organisation's level: E2 ``delivered`` (then the ``TagHooks``: the ``SUBMITTED``
   engagement and the Tier-2 auto-grant), E1 ``held_pending_verification``, E0 ``held_unclaimed``. Held tags reach
   nobody: no engagement, no grant, no email, no invitation (the prototype has none);
6. when at least one tag was delivered: the developer's in-app notification and EM1, sent after the response
   (``bridge.notifications.em1``), listing the sent and saved groups. Only the developer is written to: an
   organisation's members see delivered tags in their Inbox (``bridge.proposals.inbox``).

A per-developer advisory lock serialises one developer's Pitches, so the cap and the conflict checks cannot both pass
for two concurrent requests. The developer may withdraw a held tag (a delivered one is withdrawn on the tracker).

Tag privacy (REQ-REPO-03): tags are read here only as the developer's own; nothing in this module returns another
organisation's tag to an organisation, and teasers never carry tag data (``serializers``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.billing import entitlements
from bridge.config import Settings
from bridge.directory.schemas import Badge
from bridge.directory.service import badge_for
from bridge.errors import ApiError, not_found
from bridge.ids import uuid7
from bridge.models.enums import OrgVerification, ProvenanceStatus, TagStatus
from bridge.notifications import em1
from bridge.proposals.tag_hooks import TagHooks

TAGS_PER_PROPOSAL: Final = "tags_per_proposal"
MAX_BATCH: Final = 20  # the largest tags_per_proposal of any plan (placeholder until G3)
DECLINE_COOLDOWN: Final = "30 days"  # docs/spec/06 6.3: 30-day cooldown after a decline
IN_APP_KIND: Final = "pitch_sent"
STATUS_BY_LEVEL: Final = {
    OrgVerification.E2: TagStatus.DELIVERED,
    OrgVerification.E1: TagStatus.HELD_PENDING_VERIFICATION,
    OrgVerification.UNCLAIMED: TagStatus.HELD_UNCLAIMED,
}
HELD: Final = (TagStatus.HELD_UNCLAIMED, TagStatus.HELD_PENDING_VERIFICATION)

Reason = Literal["own_organisation", "tagged", "open_elsewhere", "already_pitched", "cooldown", "unavailable"]
# [[COPY-REVIEW]] why an organisation cannot be pitched to (shown in the picker and in a 409).
REASONS: Final[dict[str, str]] = {
    "own_organisation": "You are a member of {org}, so you cannot pitch to it.",
    "tagged": "This proposal is already pitched to {org}.",
    "open_elsewhere": (
        "You already have an open pitch with {org}. One open pitch per organisation at a time: wait for its answer"
        " or withdraw it first."
    ),
    "already_pitched": "You pitched this proposal to {org} before.",
    "cooldown": "{org} declined a pitch of yours in the last 30 days. You can pitch to them again after that.",
    "unavailable": "{org} cannot receive pitches right now.",
}


# --- request and response shapes -------------------------------------------------------------------------------------


class TagsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_ids: list[UUID] = Field(
        min_length=1, max_length=MAX_BATCH, description="Organisations to pitch to (repeats are ignored)"
    )


class TagOrg(BaseModel):
    id: UUID
    name: str
    slug: str
    badge: Badge


class TagOut(BaseModel):
    id: UUID
    org: TagOrg | None = Field(description="Null once the organisation is no longer listed")
    status: TagStatus
    open: bool
    created_at: datetime
    engagement_id: UUID | None
    message: str | None = Field(description="Why a held tag waits, and that nobody was emailed")


class TagCap(BaseModel):
    used: int
    limit: int | None = Field(description="Null means unlimited")
    plan: str


class PitchResult(BaseModel):
    tags: list[TagOut] = Field(description="The tags this Pitch created, in the order asked")
    sent_count: int
    saved_count: int
    email_sent: bool = Field(description="Whether the disclosure-record email (EM1) goes to you")
    cap: TagCap


class MyTags(BaseModel):
    items: list[TagOut]
    cap: TagCap


# --- reads -----------------------------------------------------------------------------------------------------------

_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_PROPOSAL = text(
    "SELECT id, status, moderation_state, current_version_id FROM proposals WHERE id = :id AND owner_id = :me"
)
_PROPOSAL_FOR_SHARE = text(
    "SELECT id, status, moderation_state, current_version_id FROM proposals WHERE id = :id AND owner_id = :me FOR SHARE"
)
ORGS = text(
    "SELECT id, legal_name, slug, verification, suspended_at FROM organizations WHERE id = ANY(:ids)"
    " AND verification IN ('unclaimed', 'e1', 'e2') AND delisted_at IS NULL"
)
_MEMBER_OF = text("SELECT o FROM unnest(CAST(:ids AS uuid[])) AS o WHERE app_is_member(o)")
_OPEN_TAGS = text(
    "SELECT org_id, proposal_id FROM tags WHERE developer_id = :me AND org_id = ANY(:ids) AND closed_at IS NULL"
)
_ENGAGEMENTS = text(
    "SELECT org_id, proposal_id, ended_at IS NULL AS open,"
    " state = 'DECLINED' AND ended_at > app_clock_now() - CAST(:cooldown AS interval) AS cooling"
    " FROM engagements WHERE developer_id = :me AND org_id = ANY(:ids)"
)
_USED = text(
    "SELECT count(*) FROM tags t WHERE t.proposal_id = :proposal AND t.developer_id = :me"
    " AND (t.closed_at IS NULL OR t.status IN ('delivered', 'expired') OR EXISTS (SELECT 1 FROM engagements e"
    " WHERE e.proposal_id = t.proposal_id AND e.org_id = t.org_id))"
)
_MY_TAGS = text(
    "SELECT t.id, t.org_id, t.status, t.closed_at, t.created_at, o.legal_name, o.slug, o.verification,"
    " e.id AS engagement_id FROM tags t"
    " LEFT JOIN organizations o ON o.id = t.org_id AND o.verification IN ('unclaimed', 'e1', 'e2')"
    " AND o.delisted_at IS NULL"
    " LEFT JOIN engagements e ON e.proposal_id = t.proposal_id AND e.org_id = t.org_id"
    " WHERE t.proposal_id = :proposal AND t.developer_id = :me"
    " AND (CAST(:only AS uuid[]) IS NULL OR t.id = ANY(CAST(:only AS uuid[])))"
    " ORDER BY t.created_at, t.id"
)
_RECEIPT = text(
    "SELECT v.title, v.cert_id, v.content_hash, r.status AS provenance_status FROM proposals p"
    " JOIN proposal_versions v ON v.id = p.current_version_id LEFT JOIN provenance_records r ON r.version_id = v.id"
    " WHERE p.id = :proposal"
)


async def own_proposal(db: AsyncSession, developer_id: UUID, proposal_id: UUID, *, lock: bool = False) -> Any:
    """The caller's proposal (404 for anyone else's); ``lock`` holds it FOR SHARE (no publish in between)."""
    row = (
        await db.execute(_PROPOSAL_FOR_SHARE if lock else _PROPOSAL, {"id": proposal_id, "me": developer_id})
    ).one_or_none()
    if row is None:
        raise not_found("No proposal of yours has this id.")
    return row


def is_public(proposal: Any) -> bool:
    return bool(proposal.status == "published" and proposal.moderation_state == "clear")


@dataclass(frozen=True, slots=True)
class Conflict:
    org_id: UUID
    reason: Reason

    def message(self, org_name: str) -> str:
        return REASONS[self.reason].format(org=org_name)


async def conflicts(
    db: AsyncSession, *, developer_id: UUID, proposal_id: UUID, orgs: Sequence[Any]
) -> dict[UUID, Conflict]:
    """Why each of ``orgs`` (rows of ``ORGS``) cannot be pitched to now; organisations that can are left out."""
    ids = [org.id for org in orgs]
    if not ids:
        return {}
    params = {"ids": ids, "me": developer_id, "cooldown": DECLINE_COOLDOWN}
    members = set((await db.execute(_MEMBER_OF, params)).scalars().all())
    open_tags = (await db.execute(_OPEN_TAGS, params)).all()
    engagements = (await db.execute(_ENGAGEMENTS, params)).all()
    found: dict[UUID, Conflict] = {}

    def note(org_id: UUID, reason: Reason) -> None:
        found.setdefault(org_id, Conflict(org_id, reason))

    for org_id in members:
        note(org_id, "own_organisation")
    for tag in open_tags:
        note(tag.org_id, "tagged" if tag.proposal_id == proposal_id else "open_elsewhere")
    for engagement in engagements:
        if engagement.open:
            note(engagement.org_id, "tagged" if engagement.proposal_id == proposal_id else "open_elsewhere")
    for engagement in engagements:
        if engagement.proposal_id == proposal_id:
            note(engagement.org_id, "already_pitched")
    for engagement in engagements:
        if engagement.cooling:
            note(engagement.org_id, "cooldown")
    for org in orgs:
        if org.verification == OrgVerification.E2 and org.suspended_at is not None:
            note(org.id, "unavailable")
    return found


async def cap(
    db: AsyncSession, settings: Settings, *, developer_id: UUID, proposal_id: UUID
) -> tuple[TagCap, entitlements.Entitlements]:
    """The plan cap of tags per proposal and how many of this proposal's tags count against it."""
    ent = await entitlements.for_subject(db, settings, user_id=developer_id)
    used = int((await db.execute(_USED, {"proposal": proposal_id, "me": developer_id})).scalar_one())
    return TagCap(used=used, limit=ent.limit(TAGS_PER_PROPOSAL), plan=ent.plan_code), ent


def held_message(status: TagStatus, org_name: str | None) -> str | None:
    template = em1.HELD_REASONS.get(status)
    return None if template is None else template.format(org=org_name or "This organisation")


def _tag_out(row: Any) -> TagOut:
    org = None
    if row.legal_name is not None:
        org = TagOrg(id=row.org_id, name=row.legal_name, slug=row.slug, badge=badge_for(row.verification))
    status = TagStatus(row.status)
    is_open = row.closed_at is None
    return TagOut(
        id=row.id,
        org=org,
        status=status,
        open=is_open,
        created_at=row.created_at,
        engagement_id=row.engagement_id,
        message=held_message(status, row.legal_name) if is_open else None,
    )


async def _tags(db: AsyncSession, developer_id: UUID, proposal_id: UUID, only: list[UUID] | None) -> list[TagOut]:
    params = {"proposal": proposal_id, "me": developer_id, "only": only}
    return [_tag_out(row) for row in (await db.execute(_MY_TAGS, params)).all()]


async def my_tags(db: AsyncSession, settings: Settings, *, developer_id: UUID, proposal_id: UUID) -> MyTags:
    await own_proposal(db, developer_id, proposal_id)
    tag_cap, _ = await cap(db, settings, developer_id=developer_id, proposal_id=proposal_id)
    return MyTags(items=await _tags(db, developer_id, proposal_id, None), cap=tag_cap)


# --- pitch -----------------------------------------------------------------------------------------------------------

_INSERT = text(
    "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
    " VALUES (:id, :proposal, :org, :me, CAST(:status AS tag_status))"
)
_IN_APP = text(
    "INSERT INTO in_app_notifications (id, user_id, kind, title, body, link)"
    " VALUES (:id, :me, :kind, :title, :body, :link)"
)


@dataclass(frozen=True, slots=True)
class Pitched:
    result: PitchResult
    email: em1.PendingEm1 | None


@dataclass(frozen=True, slots=True)
class Recipient:
    """The developer as EM1 addresses them, and the links EM1 carries (the platform's own)."""

    address: str
    base_url: str
    product: str


def _conflict_error(found: dict[UUID, Conflict], names: dict[UUID, str], order: Sequence[UUID]) -> ApiError:
    listed = [found[org_id] for org_id in order if org_id in found]
    return ApiError(
        409,
        "tag_conflict",
        listed[0].message(names[listed[0].org_id]),
        conflicts=[
            {"org_id": str(c.org_id), "reason": c.reason, "message": c.message(names[c.org_id])} for c in listed
        ],
    )


async def pitch(
    db: AsyncSession,
    settings: Settings,
    hooks: TagHooks,
    *,
    developer_id: UUID,
    recipient: Recipient,
    proposal_id: UUID,
    org_ids: Sequence[UUID],
) -> Pitched:
    order = list(dict.fromkeys(org_ids))
    await db.execute(_LOCK, {"key": f"tags:{developer_id}"})
    proposal = await own_proposal(db, developer_id, proposal_id, lock=True)
    if not is_public(proposal):
        raise ApiError(409, "proposal_not_public", "Publish this proposal (and wait for any review) before pitching.")
    orgs = {row.id: row for row in (await db.execute(ORGS, {"ids": order})).all()}
    missing = [str(org_id) for org_id in order if org_id not in orgs]
    if missing:
        raise ApiError(404, "not_found", "Some organisations are not in the directory.", org_ids=missing)
    names = {org_id: org.legal_name for org_id, org in orgs.items()}
    found = await conflicts(db, developer_id=developer_id, proposal_id=proposal_id, orgs=list(orgs.values()))
    if found:
        raise _conflict_error(found, names, order)
    tag_cap, ent = await cap(db, settings, developer_id=developer_id, proposal_id=proposal_id)
    entitlements.check_room(settings, ent, TAGS_PER_PROPOSAL, used=tag_cap.used, adding=len(order))

    created: list[UUID] = []
    delivered: list[UUID] = []
    engagements: list[str] = []
    try:
        for org_id in order:
            status = STATUS_BY_LEVEL[OrgVerification(orgs[org_id].verification)]
            tag_id = uuid7()
            params = {"id": tag_id, "proposal": proposal_id, "org": org_id, "me": developer_id, "status": status.value}
            await db.execute(_INSERT, params)
            created.append(tag_id)
            if status == TagStatus.DELIVERED:
                delivered.append(tag_id)
                engagement_id = await hooks.open_engagement(
                    db,
                    developer_id=developer_id,
                    proposal_id=proposal_id,
                    version_id=proposal.current_version_id,
                    org_id=org_id,
                    tag_id=tag_id,
                )
                engagements.append(str(engagement_id))
                await hooks.grant_on_tag(db, owner_id=developer_id, proposal_id=proposal_id, org_id=org_id)
    except IntegrityError as exc:  # a backstop: the lock and the checks above make this a race we lost
        await db.rollback()
        raise ApiError(409, "tag_conflict", "Something changed while pitching. Reload and try again.") from exc

    tags = await _tags(db, developer_id, proposal_id, created)
    by_id = {tag.id: tag for tag in tags}
    ordered = [by_id[tag_id] for tag_id in created]
    await audit(
        db,
        "proposal.pitched",
        actor_user_id=developer_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={
            "tag_ids": [str(tag_id) for tag_id in created],
            "delivered": len(delivered),
            "held": len(created) - len(delivered),
            "engagement_ids": engagements,
        },
    )
    email = None
    if delivered:
        email = await _receipt(db, developer_id, proposal_id, recipient, ordered, delivered)
        await db.execute(
            _IN_APP,
            {
                "id": uuid7(),
                "me": developer_id,
                "kind": IN_APP_KIND,
                "title": email.parts.subject[:200],
                "body": _in_app_body(ordered),
                "link": f"/dev/ideas/{proposal_id}",
            },
        )
    await db.commit()
    result = PitchResult(
        tags=ordered,
        sent_count=len(delivered),
        saved_count=len(created) - len(delivered),
        email_sent=email is not None,
        cap=TagCap(used=tag_cap.used + len(created), limit=tag_cap.limit, plan=tag_cap.plan),
    )
    return Pitched(result=result, email=email)


def _in_app_body(tags: list[TagOut]) -> str:
    """[[COPY-REVIEW]] the in-app line: who received it and who it is saved for."""
    sent = [tag.org.name for tag in tags if tag.status == TagStatus.DELIVERED and tag.org]
    saved = [tag.org.name for tag in tags if tag.status in HELD and tag.org]
    body = "Sent to " + ", ".join(sent) + "."
    if saved:
        body += " Saved for " + ", ".join(saved) + " until they are on the platform and verified."
    return body


async def _receipt(
    db: AsyncSession,
    developer_id: UUID,
    proposal_id: UUID,
    recipient: Recipient,
    tags: list[TagOut],
    delivered: list[UUID],
) -> em1.PendingEm1:
    row = (await db.execute(_RECEIPT, {"proposal": proposal_id})).one()
    base = recipient.base_url.rstrip("/")
    facts = em1.Em1Facts(
        title=row.title,
        cert_id=row.cert_id,
        content_sha256=None if row.content_hash is None else bytes(row.content_hash).hex(),
        timestamped=row.provenance_status == ProvenanceStatus.TIMESTAMPED,
        sent_to=tuple(tag.org.name for tag in tags if tag.status == TagStatus.DELIVERED and tag.org),
        saved_for=tuple(em1.HeldOrg(tag.org.name, tag.status) for tag in tags if tag.status in HELD and tag.org),
        proposal_url=f"{base}/dev/ideas/{proposal_id}",
        settings_url=f"{base}/settings/notifications",
        help_url=f"{base}/help",
        product=recipient.product,
    )
    return em1.PendingEm1(
        developer_id=developer_id,
        address=recipient.address,
        parts=em1.render(facts),
        dedupe_key=em1.dedupe_key(proposal_id, delivered),
    )


# --- withdraw --------------------------------------------------------------------------------------------------------

_TAG_FOR_UPDATE = text(
    "SELECT id, status, closed_at FROM tags WHERE id = :tag AND proposal_id = :proposal AND developer_id = :me"
    " FOR UPDATE"
)
_WITHDRAW = text("UPDATE tags SET status = 'withdrawn', updated_at = now() WHERE id = :tag")


async def withdraw(db: AsyncSession, *, developer_id: UUID, proposal_id: UUID, tag_id: UUID) -> TagOut:
    """Withdraw one of the caller's open held tags (it closes; the organisation never saw it)."""
    await db.execute(_LOCK, {"key": f"tags:{developer_id}"})
    await own_proposal(db, developer_id, proposal_id)
    row = (
        await db.execute(_TAG_FOR_UPDATE, {"tag": tag_id, "proposal": proposal_id, "me": developer_id})
    ).one_or_none()
    if row is None:
        raise not_found("No tag of yours has this id.")
    if row.closed_at is not None:
        raise ApiError(409, "tag_closed", "This tag is already closed.")
    if TagStatus(row.status) not in HELD:
        raise ApiError(
            409, "tag_delivered", "This proposal already reached the organisation: withdraw it on your tracker."
        )
    await db.execute(_WITHDRAW, {"tag": tag_id})
    await audit(
        db,
        "proposal.tag_withdrawn",
        actor_user_id=developer_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"tag_id": str(tag_id), "status": str(row.status)},
    )
    [tag] = await _tags(db, developer_id, proposal_id, [tag_id])
    await db.commit()
    return tag
