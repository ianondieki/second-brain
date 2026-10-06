"""Publishing and reading proposals (REQ-PROP-01, REQ-PROP-02, REQ-MOD-01, REQ-PROV-01; docs/spec/06 6.1, 6.3, 6.4).

``publish`` registers the draft version in one transaction, or changes nothing:

1. the three ownership attestations and the current attestation text version (422 otherwise);
2. the draft is complete and clean (AC-REPO-4/a: Tier-1 fields, a niche, a linked or new Problem, the sanitiser);
3. the active-proposal cap of the owner's plan for a first publication (AC-SUB-1: 402, nothing created), counted
   under a per-owner advisory lock so two publications cannot both pass it;
4. the rules pre-screen of the teaser and of a new Problem: a hold is raised in the same transaction
   (``app_hold_proposal``, a held Problem) with a ``moderation_cases`` row; a new version of a held or rejected
   proposal is queued again (it stays private until a moderator approves it); a new Problem is published at once
   and queued for moderation either way (AC-PROP-5);
5. the version becomes ``registered`` with a fresh certificate id (the database times it), the proposal points at it,
   the attestation row is written and the T2.4 registration pipeline is queued (``enqueue_registration``);
6. a ``signal_events`` row when the teaser is visible (clear: ``proposal_published`` the first time,
   ``proposal_version_published`` after), the on_new scouts' run queued (``scouts.on_new``, REQ-SCOUT-02; a failure
   to queue it never fails the publication), and the ``proposal.published`` audit event.

D1 is the route's dependency (``D1Developer``, AC-IP-5). Reads: the owner's list and detail (with their own Tier 2;
the Tier-2 read is audited) and the public teaser, which only a published, clear proposal has (a held teaser is
returned by no public endpoint until a moderator approves it, AC-PROP-6).
"""

from __future__ import annotations

import json
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.billing import entitlements
from bridge.config import Settings
from bridge.crypto.envelope import KeyWrapper
from bridge.errors import ApiError, not_found
from bridge.ids import uuid7
from bridge.llm.embeddings import Embedder
from bridge.matching.tasks import defer_on_new
from bridge.models.enums import ModerationState, ProposalStatus, ProvenanceStatus, VersionStatus
from bridge.problems import service as problems
from bridge.proposals import attestations, editor, originality, tier2
from bridge.proposals.prescreen import PreScreen, ScreenInput, listed_org_names
from bridge.proposals.schemas import (
    AttachmentOut,
    ConfidentialOut,
    ModerationOut,
    MyProposalItem,
    MyProposalOut,
    MyProposals,
    NewProblemOut,
    ProvenanceOut,
    PublishIn,
    PublishOut,
    TeaserCard,
    TeaserOut,
    VersionOut,
)
from bridge.provenance.service import enqueue_registration, new_cert_id, status_label, subject_digest

ACTIVE_PROPOSALS: Final = "active_proposals"
SIGNAL_PUBLISHED: Final = "proposal_published"  # first visible publication
SIGNAL_NEW_VERSION: Final = "proposal_version_published"  # a later version of a visible proposal
NEW_PROBLEM_REASON: Final = "new_developer_problem"
# A new version of a held or rejected proposal goes back to the moderators even when the rules raise nothing.
NEW_VERSION_REASON: Final = "new_version_of_moderated_proposal"
TEASER_COLUMNS: Final = ("title", "niche_id", "country", "county_code", "problem_statement", "impact_claims", "summary")
# [[COPY-REVIEW]] what the owner reads about moderation.
MODERATION_MESSAGES: Final = {
    ModerationState.HELD: "Held for review: only you can see this teaser until a moderator approves it.",
    ModerationState.REJECTED: "A moderator did not approve this teaser, so only you can see it.",
}


def moderation_out(state: ModerationState) -> ModerationOut:
    return ModerationOut(state=state, message=MODERATION_MESSAGES.get(state))


def provenance_out(cert_id: str, status: str | None) -> ProvenanceOut:
    stamped = status == ProvenanceStatus.TIMESTAMPED
    return ProvenanceOut(
        status="timestamped" if stamped else "timestamp_pending",
        label=status_label(ProvenanceStatus(status) if status else None),
        verify_path=f"/verify/{cert_id}",
    )


# --- reads -----------------------------------------------------------------------------------------------------------

_VERSION = text(
    "SELECT v.id, v.proposal_id, v.version_no, v.status, v.cert_id, v.registered_at, v.owner_handle, v.title,"
    " v.niche_id, v.country, v.county_code, v.maturity, v.ask, v.problem_statement, v.impact_claims, v.summary,"
    " n.slug AS niche_slug, n.name_en AS niche_name, pn.name_en AS parent_name, r.status AS provenance_status"
    " FROM proposal_versions v LEFT JOIN niches n ON n.id = v.niche_id LEFT JOIN niches pn ON pn.id = n.parent_id"
    " LEFT JOIN provenance_records r ON r.version_id = v.id WHERE v.id = :version"
)
_ATTACHMENT_ROWS = text(
    "SELECT id, sha256, size_bytes, content_type, av_status FROM proposal_attachments WHERE version_id = :version"
    " ORDER BY created_at, id"
)


def teaser_out(row: Any) -> TeaserOut:
    return TeaserOut(
        title=row.title,
        niche=problems.niche_out(row.niche_id, row.niche_slug, row.niche_name, row.parent_name),
        country=row.country,
        county_code=row.county_code,
        maturity=row.maturity,
        ask=row.ask,
        problem_statement=row.problem_statement,
        impact_claims=row.impact_claims,
        summary=row.summary,
    )


async def _version_row(db: AsyncSession, version_id: UUID) -> Any:
    row = (await db.execute(_VERSION, {"version": version_id})).one_or_none()
    if row is None:
        raise not_found()
    return row


async def _version_out(db: AsyncSession, wrapper: KeyWrapper, proposal_id: UUID, version_id: UUID) -> VersionOut:
    row = await _version_row(db, version_id)
    document = await tier2.load(db, wrapper, proposal_id, version_id)
    body = document.body if document is not None else tier2.empty_document()
    names = {e.get("id"): e.get("file_name") for e in body.get("attachments", [])}
    attachments = [
        AttachmentOut(
            id=a.id,
            file_name=names.get(str(a.id)),
            content_type=a.content_type,
            size_bytes=a.size_bytes,
            sha256=None if a.sha256 is None else bytes(a.sha256).hex(),
            av_status=a.av_status,
        )
        for a in (await db.execute(_ATTACHMENT_ROWS, {"version": version_id})).all()
    ]
    pending = body.get(tier2.DRAFT_KEY, {}).get("new_problem")
    registered = row.status == VersionStatus.REGISTERED
    return VersionOut(
        id=row.id,
        version_no=row.version_no,
        status=row.status,
        cert_id=row.cert_id,
        registered_at=row.registered_at,
        provenance=provenance_out(row.cert_id, row.provenance_status) if registered else None,
        teaser=teaser_out(row),
        problems=await problems.refs_for_version(db, version_id, public=False),
        new_problem=None if pending is None else NewProblemOut(**pending),
        confidential=ConfidentialOut(
            **{name: body.get(name) for name in tier2.TEXT_FIELDS},
            links=list(body.get("links", [])),
            attachments=attachments,
        ),
    )


_MINE = text(
    "SELECT id, status, moderation_state, published_at, hidden_at, current_version_id, draft_version_id,"
    " coalesce(app_contributor_handles(id), '{}') AS contributors"  # D-62 (a), REQ-DEV-03: never the manifest's
    " FROM proposals WHERE id = :id AND owner_id = :user"
)


async def my_proposal(db: AsyncSession, wrapper: KeyWrapper, user_id: UUID, proposal_id: UUID) -> MyProposalOut:
    """One of the caller's proposals with both versions and their own Tier 2 (the read is audited)."""
    row = (await db.execute(_MINE, {"id": proposal_id, "user": user_id})).one_or_none()
    if row is None:
        raise not_found("No proposal of yours has this id.")
    current = (
        None if row.current_version_id is None else await _version_out(db, wrapper, row.id, row.current_version_id)
    )
    draft = None if row.draft_version_id is None else await _version_out(db, wrapper, row.id, row.draft_version_id)
    versions = [str(v.id) for v in (current, draft) if v is not None]
    await audit(
        db,
        "proposal.tier2_read",
        actor_user_id=user_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"version_ids": versions, "by_owner": True},
    )
    await db.commit()
    return MyProposalOut(
        id=row.id,
        status=row.status,
        moderation=moderation_out(ModerationState(row.moderation_state)),
        published_at=row.published_at,
        hidden_at=row.hidden_at,
        current=current,
        draft=draft,
        contributors=list(row.contributors),
    )


_MY_LIST = text(
    "SELECT p.id, p.status, p.moderation_state, p.published_at, p.draft_version_id IS NOT NULL AS has_draft,"
    " cv.version_no AS current_version_no, cv.cert_id, coalesce(dv.title, cv.title) AS title,"
    " n.id AS niche_id, n.slug AS niche_slug, n.name_en AS niche_name, pn.name_en AS parent_name,"
    " greatest(p.updated_at, dv.updated_at) AS updated_at"
    " FROM proposals p LEFT JOIN proposal_versions cv ON cv.id = p.current_version_id"
    " LEFT JOIN proposal_versions dv ON dv.id = p.draft_version_id"
    " LEFT JOIN niches n ON n.id = coalesce(dv.niche_id, cv.niche_id) LEFT JOIN niches pn ON pn.id = n.parent_id"
    " WHERE p.owner_id = :user ORDER BY greatest(p.updated_at, dv.updated_at) DESC, p.id DESC LIMIT 200"
)


async def my_proposals(db: AsyncSession, user_id: UUID) -> MyProposals:
    """The caller's proposals ("My ideas"), most recently changed first (Tier 1 only)."""
    rows = (await db.execute(_MY_LIST, {"user": user_id})).all()
    return MyProposals(
        items=[
            MyProposalItem(
                id=r.id,
                status=r.status,
                moderation_state=r.moderation_state,
                title=r.title,
                niche=problems.niche_out(r.niche_id, r.niche_slug, r.niche_name, r.parent_name),
                current_version_no=r.current_version_no,
                cert_id=r.cert_id,
                has_draft=r.has_draft,
                published_at=r.published_at,
                updated_at=r.updated_at,
            )
            for r in rows
        ]
    )


_PUBLIC = text(
    "SELECT current_version_id, coalesce(app_contributor_handles(id), '{}') AS contributors"  # D-62 (a)
    " FROM proposals WHERE id = :id AND status = 'published' AND moderation_state = 'clear'"
)


async def teaser_card(db: AsyncSession, proposal_id: UUID) -> TeaserCard:
    """A published, clear proposal's current teaser (Tier 1 only); 404 for anything else, the owner included."""
    found = (await db.execute(_PUBLIC, {"id": proposal_id})).one_or_none()
    if found is None or found.current_version_id is None:
        raise not_found()
    version_id = found.current_version_id
    row = await _version_row(db, version_id)
    return TeaserCard(
        id=proposal_id,
        owner_handle=row.owner_handle,
        cert_id=row.cert_id,
        version_no=row.version_no,
        registered_at=row.registered_at,
        provenance=provenance_out(row.cert_id, row.provenance_status),
        teaser=teaser_out(row),
        problems=await problems.refs_for_version(db, version_id, public=True),
        contributors=list(found.contributors),
    )


# --- publish ---------------------------------------------------------------------------------------------------------

_OWNER_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_ACTIVE = text("SELECT count(*) FROM proposals WHERE owner_id = :user AND status = 'published'")
_LINKED = text("SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :version")
_LINK = text("INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:version, :problem)")
_REGISTER = text(
    "UPDATE proposal_versions SET status = 'registered', cert_id = :cert_id, updated_at = now()"
    " WHERE id = :version AND status = 'draft'"
)
_PUBLISH = text(
    "UPDATE proposals SET status = 'published', current_version_id = :version, draft_version_id = NULL,"
    " published_at = coalesce(published_at, now()), title = :title, niche_id = :niche_id, country = :country,"
    " county_code = :county_code, maturity = CAST(:maturity AS proposal_maturity),"
    " ask = CAST(:ask AS proposal_ask), problem_statement = :problem_statement, impact_claims = :impact_claims,"
    " summary = :summary, updated_at = now() WHERE id = :id"
)
_HOLD = text("SELECT app_hold_proposal(:id)")
_ATTEST = text(
    "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
    " no_third_party_confidential, text_version, text_sha256) VALUES (:id, :user, :version, true, true, true,"
    " :text_version, :text_sha256)"
)
_SIGNAL = text("INSERT INTO signal_events (id, item_id, kind, actor_hash) VALUES (:id, :item, :kind, :actor)")
SIGNAL_ACTOR = b"signal_events.actor"


def _check_attestations(body: PublishIn) -> None:
    if body.attestation_text_version != attestations.VERSION:
        raise ApiError(409, "attestation_text_outdated", "The attestation text changed. Read it again and confirm.")
    missing = [name for name, value in body.attestations.model_dump().items() if value is not True]
    if missing:
        raise ApiError(422, "attestations_required", "Confirm all three statements to publish.", missing=missing)


async def signal(db: AsyncSession, *, proposal_id: UUID, owner_id: UUID, kind: str = SIGNAL_PUBLISHED) -> None:
    """The cross-org signal of a visible publication (ids and a per-subject salted hash only)."""
    actor = await subject_digest(db, owner_id, SIGNAL_ACTOR)
    await db.execute(_SIGNAL, {"id": uuid7(), "item": proposal_id, "kind": kind, "actor": actor})


async def publish(
    db: AsyncSession,
    settings: Settings,
    wrapper: KeyWrapper,
    prescreen: PreScreen,
    embedder: Embedder,
    *,
    user_id: UUID,
    proposal_id: UUID,
    body: PublishIn,
) -> PublishOut:
    _check_attestations(body)
    await db.execute(_OWNER_LOCK, {"key": f"proposals.publish:{user_id}"})
    locked = await editor.lock_own(db, user_id, proposal_id)
    editor.refuse_closed(locked)
    if locked.draft_version_id is None:
        raise ApiError(409, "nothing_to_publish", "There are no changes to publish.")
    version_id = locked.draft_version_id
    row = await _version_row(db, version_id)
    document = await tier2.load(db, wrapper, proposal_id, version_id)
    if document is None:
        raise ApiError(409, "nothing_to_publish", "This draft's confidential part is missing.")
    new_problem: dict[str, Any] | None = document.body.get(tier2.DRAFT_KEY, {}).get("new_problem")
    # Only a published, clear problem counts: one rejected or held after it was linked does not.
    linked = await problems.linkable(db, (await db.execute(_LINKED, {"version": version_id})).scalars().all())
    values = row._asdict()
    errors = editor.publish_errors(values, has_problem=bool(linked) or new_problem is not None, new_problem=new_problem)
    if errors:
        raise editor.invalid("cannot_publish", "Some fields need attention before publishing.", errors)
    if locked.status != ProposalStatus.PUBLISHED:
        ent = await entitlements.for_subject(db, settings, user_id=user_id)
        used = int((await db.execute(_ACTIVE, {"user": user_id})).scalar_one())
        entitlements.check_count(settings, ent, ACTIVE_PROPOSALS, used=used)

    org_names = await listed_org_names(db)
    fields = {name: values[name] for name in editor.TEXT_FIELDS if values.get(name)}
    teaser_screen = await prescreen.screen(ScreenInput(fields, org_names))
    new_problem_id = None
    if new_problem is not None:
        text_fields = {"title": new_problem["title"], "statement": new_problem["statement"]}
        problem_screen = await prescreen.screen(ScreenInput(text_fields, org_names))
        niche = new_problem.get("niche_id") or row.niche_id
        new_problem_id = await problems.create_developer_problem(
            db, user_id=user_id, niche_id=niche, held=problem_screen.hold, **text_fields
        )
        await db.execute(_LINK, {"version": version_id, "problem": new_problem_id})
        classifier = None if problem_screen.classifier is None else json.dumps(problem_screen.classifier)
        reasons = [NEW_PROBLEM_REASON, *problem_screen.reasons]
        await problems.open_case(db, "problem", new_problem_id, reasons, classifier)
    if tier2.DRAFT_KEY in document.body:  # draft-only data never reaches the registered document
        del document.body[tier2.DRAFT_KEY]
        await tier2.save(db, document, owner_id=user_id, new=False)

    cert_id = new_cert_id()
    await db.execute(_REGISTER, {"cert_id": cert_id, "version": version_id})
    teaser = {name: values[name] for name in TEASER_COLUMNS}
    maturity_ask = {"maturity": str(row.maturity), "ask": str(row.ask)}
    await db.execute(_PUBLISH, {"id": proposal_id, "version": version_id, **teaser, **maturity_ask})
    await originality.index_teaser(db, embedder, proposal_id=proposal_id, fields=teaser)  # REQ-PROP-04: Tier 1 only
    state = locked.moderation_state
    if teaser_screen.hold:
        await db.execute(_HOLD, {"id": proposal_id})
        state = ModerationState.HELD if state == ModerationState.CLEAR else state
    if teaser_screen.hold or state != ModerationState.CLEAR:
        classifier = None if teaser_screen.classifier is None else json.dumps(teaser_screen.classifier)
        teaser_reasons = teaser_screen.reasons or (NEW_VERSION_REASON,)
        await problems.open_case(db, "proposal", proposal_id, teaser_reasons, classifier)
    await db.execute(
        _ATTEST,
        {
            "id": uuid7(),
            "user": user_id,
            "version": version_id,
            "text_version": attestations.VERSION,
            "text_sha256": attestations.text_digest(),
        },
    )
    await enqueue_registration(db, version_id)
    if state == ModerationState.CLEAR:
        kind = SIGNAL_PUBLISHED if locked.status != ProposalStatus.PUBLISHED else SIGNAL_NEW_VERSION
        await signal(db, proposal_id=proposal_id, owner_id=user_id, kind=kind)
        await defer_on_new(db, proposal_id)
    await audit(
        db,
        "proposal.published",
        actor_user_id=user_id,
        subject_type="proposal_version",
        subject_id=version_id,
        payload={
            "proposal_id": str(proposal_id),
            "version_no": row.version_no,
            "cert_id": cert_id,
            "moderation_state": state.value,
            "new_problem_id": None if new_problem_id is None else str(new_problem_id),
        },
    )
    await db.commit()
    return PublishOut(
        proposal_id=proposal_id,
        version_id=version_id,
        version_no=row.version_no,
        cert_id=cert_id,
        status=ProposalStatus.PUBLISHED,
        moderation=moderation_out(state),
        provenance=provenance_out(cert_id, None),
        new_problem_id=new_problem_id,
    )
