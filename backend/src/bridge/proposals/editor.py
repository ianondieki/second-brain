"""The proposal editor's writes (REQ-PROP-01; docs/spec/06 6.1, 6.3): drafts, their attachments, and the publish
validation. Publishing itself is ``bridge.proposals.service.publish``.

A draft is Tier 0, its owner's only: a ``draft`` ``proposal_versions`` row (Tier 1), its linked problems and its
sealed Tier-2 document (``bridge.proposals.tier2``). Editing a published proposal starts the next version as a copy
of the current one (Tier 1, still-visible linked problems, Tier 2, attachments); the registered versions never change.
Tier-1 text is sanitised on every save (``bridge.proposals.sanitise``: 422 with the fields) and again at publishing.
Every write locks the proposal row first, so one owner's concurrent saves apply one after the other.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final
from uuid import UUID

from sqlalchemy import insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.crypto.envelope import KeyWrapper
from bridge.errors import ApiError, not_found
from bridge.ids import uuid7
from bridge.models.enums import AvStatus, ModerationState, ProposalStatus
from bridge.problems import service as problems
from bridge.proposals import tier2
from bridge.proposals.models import Proposal, ProposalProblem, ProposalVersion
from bridge.proposals.sanitise import FieldError, check_field, sanitise
from bridge.proposals.schemas import AttachmentOut, DraftIn, NewProblemIn, TeaserIn
from bridge.storage.objects import ObjectStore
from bridge.storage.scanner import Scanner, Verdict

MAX_ATTACHMENTS: Final = 10
UPLOADS: Final = "uploads"
TEXT_FIELDS: Final = ("title", "problem_statement", "impact_claims", "summary")
# Magic bytes per accepted type (docs/spec/06 6.1: PDF, PNG, JPG, MD, TXT); text types must be UTF-8.
ACCEPTED_TYPES: Final[Mapping[str, bytes | None]] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "text/markdown": None,
    "text/plain": None,
}
# [[COPY-REVIEW]] what each missing field asks for.
REQUIRED: Final[Mapping[str, str]] = {
    "title": "Add a title.",
    "niche_id": "Choose a niche.",
    "maturity": "Choose how mature it is.",
    "ask": "Choose what you are asking for.",
    "problem_statement": "Describe the problem it solves.",
    "summary": "Add a short summary of what it does.",
}
PROBLEM_REQUIRED: Final = "Link a Problem or describe a new one."


@dataclass(frozen=True, slots=True)
class Locked:
    id: UUID
    status: ProposalStatus
    moderation_state: ModerationState
    current_version_id: UUID | None
    draft_version_id: UUID | None


def invalid(code: str, message: str, errors: list[FieldError]) -> ApiError:
    return ApiError(
        422, code, message, errors=[{"field": e.field, "code": e.code, "message": e.message} for e in errors]
    )


_LOCK = text(
    "SELECT id, status, moderation_state, current_version_id, draft_version_id FROM proposals"
    " WHERE id = :id AND owner_id = :user FOR UPDATE"
)


async def lock_own(db: AsyncSession, user_id: UUID, proposal_id: UUID) -> Locked:
    """The caller's proposal, locked until the transaction ends; 404 for anyone else's (or none)."""
    row = (await db.execute(_LOCK, {"id": proposal_id, "user": user_id})).one_or_none()
    if row is None:
        raise not_found("No proposal of yours has this id.")
    return Locked(
        row.id,
        ProposalStatus(row.status),
        ModerationState(row.moderation_state),
        row.current_version_id,
        row.draft_version_id,
    )


def refuse_closed(locked: Locked) -> None:
    if locked.status in (ProposalStatus.HIDDEN, ProposalStatus.ARCHIVED):
        raise ApiError(409, "proposal_hidden", "This proposal was deleted; its record is kept but it cannot change.")


# --- validation ------------------------------------------------------------------------------------------------------


def clean_teaser(teaser: TeaserIn | None) -> dict[str, Any]:
    """The teaser fields that were sent, text fields as plain text; 422 ``invalid_teaser`` on contact details."""
    if teaser is None:
        return {}
    values = {name: getattr(teaser, name) for name in teaser.model_fields_set}
    cleaned, errors = sanitise({name: values[name] for name in TEXT_FIELDS if name in values})
    if errors:
        raise invalid("invalid_teaser", "Some teaser fields need changes.", errors)
    return values | cleaned


def clean_new_problem(problem: NewProblemIn) -> dict[str, Any]:
    cleaned, errors = sanitise({"new_problem.title": problem.title, "new_problem.statement": problem.statement})
    if errors:
        raise invalid("invalid_teaser", "The new problem needs changes.", errors)
    if not cleaned["new_problem.title"] or not cleaned["new_problem.statement"]:
        raise ApiError(422, "invalid_teaser", "Give the new problem a title and a statement.")
    niche = None if problem.niche_id is None else str(problem.niche_id)
    return {"title": cleaned["new_problem.title"], "statement": cleaned["new_problem.statement"], "niche_id": niche}


def publish_errors(
    values: Mapping[str, Any], *, has_problem: bool, new_problem: Mapping[str, Any] | None = None
) -> list[FieldError]:
    """Why a draft cannot be published (AC-REPO-4/a): a missing Tier-1 field or niche, no linked or new Problem, or
    Tier-1 text the sanitiser refuses (contact details, a summary over 150 words)."""
    errors = [FieldError(name, "required", message) for name, message in REQUIRED.items() if not values.get(name)]
    if not has_problem:
        errors.append(FieldError("problems", "problem_required", PROBLEM_REQUIRED))
    for name in TEXT_FIELDS:
        if values.get(name):
            errors.extend(check_field(name, values[name]))
    if new_problem is not None:
        for name in ("title", "statement"):
            errors.extend(check_field(f"new_problem.{name}", str(new_problem.get(name) or "")))
    return errors


_ACTIVE_NICHES = text("SELECT id FROM niches WHERE id = ANY(:ids) AND active")
_COUNTY = text("SELECT 1 FROM regions WHERE code = :code AND kind = 'county'")


async def check_references(
    db: AsyncSession, values: Mapping[str, Any], problem_ids: list[UUID] | None, new_problem: NewProblemIn | None
) -> None:
    """422 for an unknown or inactive niche, an unknown county or a problem that cannot be linked."""
    niches = {n for n in (values.get("niche_id"), new_problem.niche_id if new_problem else None) if n is not None}
    if niches and len((await db.execute(_ACTIVE_NICHES, {"ids": list(niches)})).all()) != len(niches):
        raise ApiError(422, "unknown_niche", "Choose a niche from the list.")
    county = values.get("county_code")
    if county is not None and (await db.execute(_COUNTY, {"code": county})).first() is None:
        raise ApiError(422, "unknown_county", "Choose a county from the list.")
    if problem_ids and await problems.linkable(db, problem_ids) != set(problem_ids):
        raise ApiError(422, "unknown_problem", "Link only published problems from the picker.")


# --- drafts ----------------------------------------------------------------------------------------------------------


def _apply_confidential(body: dict[str, Any], draft: DraftIn) -> None:
    if draft.confidential is not None:
        for name in draft.confidential.model_fields_set:
            value = getattr(draft.confidential, name)
            body[name] = list(value or []) if name == "links" else value
    if "new_problem" in draft.model_fields_set:
        body.pop(tier2.DRAFT_KEY, None)
        if draft.new_problem is not None:
            body[tier2.DRAFT_KEY] = {"new_problem": clean_new_problem(draft.new_problem)}


async def _link_problems(db: AsyncSession, version_id: UUID, problem_ids: list[UUID]) -> None:
    await db.execute(text("DELETE FROM proposal_problems WHERE proposal_version_id = :v"), {"v": version_id})
    if problem_ids:
        await db.execute(
            insert(ProposalProblem), [{"proposal_version_id": version_id, "problem_id": p} for p in problem_ids]
        )


async def create_draft(db: AsyncSession, wrapper: KeyWrapper, user_id: UUID, draft: DraftIn) -> UUID:
    """A new proposal with its first draft version; committed. Returns the proposal id."""
    values = clean_teaser(draft.teaser)
    problem_ids = list(dict.fromkeys(draft.problem_ids or []))
    await check_references(db, values, problem_ids, draft.new_problem)
    body = tier2.empty_document()
    _apply_confidential(body, draft)  # validates the new problem before anything is written
    proposal_id, version_id = uuid7(), uuid7()
    await db.execute(insert(Proposal).values(id=proposal_id, owner_id=user_id))
    await db.execute(insert(ProposalVersion).values(id=version_id, proposal_id=proposal_id, version_no=1, **values))
    await db.execute(_SET_DRAFT, {"version": version_id, "id": proposal_id})
    await _link_problems(db, version_id, problem_ids)
    document = tier2.Document(proposal_id, version_id, await tier2.proposal_key(db, wrapper, proposal_id), body)
    await tier2.save(db, document, owner_id=user_id, new=True)
    await audit(db, "proposal.draft_created", actor_user_id=user_id, subject_type="proposal", subject_id=proposal_id)
    await db.commit()
    return proposal_id


_NEXT_VERSION = text(
    "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, country, county_code, maturity, ask,"
    " problem_statement, impact_claims, summary) SELECT :new, proposal_id,"
    " (SELECT max(version_no) + 1 FROM proposal_versions WHERE proposal_id = :proposal), title, niche_id, country,"
    " county_code, maturity, ask, problem_statement, impact_claims, summary FROM proposal_versions WHERE id = :current"
)
_COPY_PROBLEMS = text(
    "INSERT INTO proposal_problems (proposal_version_id, problem_id) SELECT :new, pp.problem_id"
    " FROM proposal_problems pp JOIN problems pr ON pr.id = pp.problem_id WHERE pp.proposal_version_id = :current"
    " AND pr.status = 'published' AND pr.moderation_state = 'clear'"
)
_ATTACHMENTS = text(
    "SELECT id, sha256, size_bytes, content_type, av_status, rerendered FROM proposal_attachments"
    " WHERE version_id = :version ORDER BY created_at, id"
)
_INSERT_ATTACHMENT = text(
    "INSERT INTO proposal_attachments (id, owner_id, proposal_id, version_id, sha256, size_bytes, content_type,"
    " av_status, rerendered) VALUES (:id, :owner, :proposal, :version, :sha256, :size, :content_type,"
    " CAST(:av_status AS av_status), :rerendered)"
)
_SET_DRAFT = text("UPDATE proposals SET draft_version_id = :version, updated_at = now() WHERE id = :id")


async def ensure_draft(db: AsyncSession, wrapper: KeyWrapper, user_id: UUID, locked: Locked) -> UUID:
    """The draft version, starting the next version from the current one when there is none."""
    if locked.draft_version_id is not None:
        return locked.draft_version_id
    current = locked.current_version_id
    if current is None:  # a proposal always has a draft or a registered version
        raise ApiError(409, "nothing_to_edit", "This proposal has no version to edit.")
    new_id = uuid7()
    params = {"new": new_id, "proposal": locked.id, "current": current}
    await db.execute(_NEXT_VERSION, params)
    await db.execute(_COPY_PROBLEMS, params)
    document = await tier2.load(db, wrapper, locked.id, current)
    if document is None:
        raise ApiError(409, "nothing_to_edit", "This proposal's confidential part is missing.")
    renamed: dict[str, str] = {}
    for row in (await db.execute(_ATTACHMENTS, {"version": current})).all():
        renamed[str(row.id)] = str(copy_id := uuid7())
        await db.execute(
            _INSERT_ATTACHMENT,
            {
                "id": copy_id,
                "owner": user_id,
                "proposal": locked.id,
                "version": new_id,
                "sha256": row.sha256,
                "size": row.size_bytes,
                "content_type": row.content_type,
                "av_status": str(row.av_status),
                "rerendered": row.rerendered,
            },
        )
    entries = document.body.get("attachments", [])
    document.body["attachments"] = [e | {"id": renamed[e["id"]]} for e in entries if e.get("id") in renamed]
    await tier2.save(db, tier2.Document(locked.id, new_id, document.key, document.body), owner_id=user_id, new=True)
    await db.execute(_SET_DRAFT, {"version": new_id, "id": locked.id})
    return new_id


async def save_draft(db: AsyncSession, wrapper: KeyWrapper, user_id: UUID, proposal_id: UUID, draft: DraftIn) -> None:
    """Apply a partial draft (starting the next version of a published proposal); committed."""
    locked = await lock_own(db, user_id, proposal_id)
    refuse_closed(locked)
    values = clean_teaser(draft.teaser)
    problem_ids = None if draft.problem_ids is None else list(dict.fromkeys(draft.problem_ids))
    await check_references(db, values, problem_ids, draft.new_problem)
    version_id = await ensure_draft(db, wrapper, user_id, locked)
    if values:
        stmt = update(ProposalVersion).where(ProposalVersion.id == version_id).values(**values)
        await db.execute(stmt.execution_options(synchronize_session=False))
    if problem_ids is not None:
        await _link_problems(db, version_id, problem_ids)
    if draft.confidential is not None or "new_problem" in draft.model_fields_set:
        document = await tier2.load(db, wrapper, proposal_id, version_id)
        if document is None:
            raise ApiError(409, "nothing_to_edit", "This draft's confidential part is missing.")
        _apply_confidential(document.body, draft)
        await tier2.save(db, document, owner_id=user_id, new=False)
    await audit(
        db,
        "proposal.draft_saved",
        actor_user_id=user_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"version_id": str(version_id)},
    )
    await db.commit()


# --- attachments -----------------------------------------------------------------------------------------------------


def attachment_problem(content_type: str, data: bytes) -> str | None:
    """Why the bytes are not an accepted attachment of that type, or None."""
    if content_type not in ACCEPTED_TYPES:
        return "Attach a PDF, PNG, JPG, Markdown or plain-text file."
    magic = ACCEPTED_TYPES[content_type]
    if magic is not None and not data.startswith(magic):
        return "The file's content does not match its type."
    if magic is None:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return "Text files must be UTF-8."
    return None


def object_key(proposal_id: UUID, attachment_id: UUID) -> str:
    """Ids only: object keys never carry file names or personal data (docs/spec/06 6.1)."""
    return f"attachments/{proposal_id}/{attachment_id}"


async def add_attachment(
    db: AsyncSession,
    wrapper: KeyWrapper,
    store: ObjectStore,
    scanner: Scanner,
    *,
    user_id: UUID,
    proposal_id: UUID,
    data: bytes,
    content_type: str,
    file_name: str,
) -> AttachmentOut:
    """Scan, store and attach a file to the draft; committed. An infected file is refused (422) and only its refusal
    is recorded."""
    locked = await lock_own(db, user_id, proposal_id)
    refuse_closed(locked)
    reason = attachment_problem(content_type, data)
    if reason is not None:
        raise ApiError(422, "unsupported_file", reason)
    verdict = await scanner.scan(data)
    if verdict.verdict != Verdict.CLEAN:
        await audit(
            db,
            "proposal.attachment_rejected",
            actor_user_id=user_id,
            subject_type="proposal",
            subject_id=proposal_id,
            payload={"scanner": scanner.name, "verdict": verdict.verdict.value, "signature": verdict.signature},
        )
        await db.commit()
        raise ApiError(422, "attachment_infected", "This file did not pass the malware scan, so it was not kept.")
    version_id = await ensure_draft(db, wrapper, user_id, locked)
    existing = (await db.execute(_ATTACHMENTS, {"version": version_id})).all()
    if len(existing) >= MAX_ATTACHMENTS:
        raise ApiError(409, "too_many_attachments", f"A version can have up to {MAX_ATTACHMENTS} attachments.")
    document = await tier2.load(db, wrapper, proposal_id, version_id)
    if document is None:
        raise ApiError(409, "nothing_to_edit", "This draft's confidential part is missing.")
    attachment_id, digest = uuid7(), hashlib.sha256(data).digest()
    key = object_key(proposal_id, attachment_id)
    await store.put(UPLOADS, key, data, content_type=content_type)
    await db.execute(
        _INSERT_ATTACHMENT,
        {
            "id": attachment_id,
            "owner": user_id,
            "proposal": proposal_id,
            "version": version_id,
            "sha256": digest,
            "size": len(data),
            "content_type": content_type,
            "av_status": AvStatus.CLEAN.value,
            "rerendered": False,
        },
    )
    document.body.setdefault("attachments", []).append(
        {"id": str(attachment_id), "file_name": file_name, "object_key": key}
    )
    await tier2.save(db, document, owner_id=user_id, new=False)
    await audit(
        db,
        "proposal.attachment_added",
        actor_user_id=user_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"attachment_id": str(attachment_id), "size_bytes": len(data), "scanner": scanner.name},
    )
    await db.commit()
    return AttachmentOut(
        id=attachment_id,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest.hex(),
        av_status=AvStatus.CLEAN,
    )


_DELETE_ATTACHMENT = text("DELETE FROM proposal_attachments WHERE id = :id AND version_id = :version")


async def remove_attachment(
    db: AsyncSession,
    wrapper: KeyWrapper,
    store: ObjectStore,
    *,
    user_id: UUID,
    proposal_id: UUID,
    attachment_id: UUID,
) -> None:
    """Remove an attachment from the draft; committed. Registered versions keep theirs (and their objects)."""
    locked = await lock_own(db, user_id, proposal_id)
    refuse_closed(locked)
    version_id = locked.draft_version_id
    deleted = 0
    if version_id is not None:
        result = await db.execute(_DELETE_ATTACHMENT, {"id": attachment_id, "version": version_id})
        deleted = int(getattr(result, "rowcount", 0))
    if version_id is None or deleted != 1:
        raise not_found("This draft has no such attachment.")
    document = await tier2.load(db, wrapper, proposal_id, version_id)
    if document is None:
        raise ApiError(409, "nothing_to_edit", "This draft's confidential part is missing.")
    entries = document.body.get("attachments", [])
    keys = [e.get("object_key") for e in entries if e.get("id") == str(attachment_id)]
    document.body["attachments"] = [e for e in entries if e.get("id") != str(attachment_id)]
    await tier2.save(db, document, owner_id=user_id, new=False)
    await audit(
        db,
        "proposal.attachment_removed",
        actor_user_id=user_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"attachment_id": str(attachment_id)},
    )
    await db.commit()
    own = object_key(proposal_id, attachment_id)
    if own in keys:  # uploaded to this draft; a copied entry points at a registered version's object, which stays
        await store.delete(UPLOADS, own)
