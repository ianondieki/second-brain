"""Deleting a proposal (REQ-PROV-05; docs/spec/06 6.4, AC-IP-6).

A proposal with a registered version is evidence: deleting it sets it ``hidden`` (gone from every Tier-1 read, and the
Tier-2 predicate admits only published proposals, so grants stop) but keeps its versions, manifests, provenance
records, attestations, proofs and audit events; certificates and ``/verify`` keep working. A proposal that was never
registered is removed with its draft, attachments and their uploaded objects. The web app states this before the owner
confirms (T2.10 frontend half).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.models.enums import ProposalStatus
from bridge.proposals import editor
from bridge.proposals.schemas import RemovedOut
from bridge.storage.objects import ObjectStore

# [[COPY-REVIEW]]
HIDDEN_MESSAGE: Final = (
    "Hidden: nobody else can see it any more. Its registered versions, certificates and proofs are kept, and"
    " /verify still works."
)
DELETED_MESSAGE: Final = "Deleted: it was never published, so nothing was kept."

_HIDE = text(
    "UPDATE proposals SET status = 'hidden', hidden_at = now(), updated_at = now()"
    " WHERE id = :id AND status <> 'hidden'"
)
_DRAFT_KEYS = text("SELECT id FROM proposal_attachments WHERE proposal_id = :id")
_UNLINK_DRAFT = text("UPDATE proposals SET draft_version_id = NULL WHERE id = :id")
_DELETE = text("DELETE FROM proposals WHERE id = :id AND status = 'draft' AND current_version_id IS NULL")


async def remove(db: AsyncSession, store: ObjectStore, *, user_id: UUID, proposal_id: UUID) -> RemovedOut:
    locked = await editor.lock_own(db, user_id, proposal_id)
    if locked.current_version_id is not None or locked.status != ProposalStatus.DRAFT:
        await db.execute(_HIDE, {"id": proposal_id})
        await audit(db, "proposal.hidden", actor_user_id=user_id, subject_type="proposal", subject_id=proposal_id)
        await db.commit()
        return RemovedOut(status="hidden", message=HIDDEN_MESSAGE)
    attachment_ids = (await db.execute(_DRAFT_KEYS, {"id": proposal_id})).scalars().all()
    await db.execute(_UNLINK_DRAFT, {"id": proposal_id})
    await db.execute(_DELETE, {"id": proposal_id})  # its draft version, Tier 2, links and attachments cascade
    await audit(db, "proposal.draft_deleted", actor_user_id=user_id, subject_type="proposal", subject_id=proposal_id)
    await db.commit()
    for attachment_id in attachment_ids:
        await store.delete(editor.UPLOADS, editor.object_key(proposal_id, attachment_id))
    return RemovedOut(status="deleted", message=DELETED_MESSAGE)
