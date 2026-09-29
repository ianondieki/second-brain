"""Tier-2 views: the render request and the access log (REQ-PROV-03, REQ-REPO-01; docs/spec/06 6.1, 6.4 item 3).

``render`` runs after ``can_view_tier2`` passed. It reads the version's Tier 2 as ``tier2_reader`` (whose policy is
``app_tier2_granted`` again), writes the ``document_views`` row whose id is the ``view_id`` printed on the page (its
INSERT policy repeats the grant check, and the time is the database's) and a ``tier2.viewed`` audit event (ids only)
on the organisation's chain, and commits before the page is returned: a view that cannot be logged is not served.
The owner's own preview is audited as an owner read and not logged as a view.

``who_has_seen`` is the owner's "Who has seen this" panel: organisation, person, time, coarse duration and NDA version
of every view of their proposal, newest first. The coarse duration needs a client heartbeat that comes after the
prototype, so it is empty for now.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth.sessions import LiveSession
from bridge.config import Settings
from bridge.crypto.envelope import KeyWrapper
from bridge.errors import not_found
from bridge.ids import uuid7
from bridge.models.enums import RenderKind, ViewDuration
from bridge.proposals import render as pages
from bridge.proposals import tier2
from bridge.proposals.access import Access
from bridge.provenance.certificate import verify_url

VIEWED: Final = "tier2.viewed"
OWNER_READ: Final = "proposal.tier2_read"
MAX_VIEWS: Final = 500
# [[COPY-REVIEW]] shown under the panel.
PANEL_NOTE: Final = (
    "Every organisation viewer accepted the Evaluation NDA and was told that you see their name and each view."
)

_OWNER_NAME = text("SELECT display_name FROM users WHERE id = :id")
_ORG_NAME = text("SELECT legal_name FROM organizations WHERE id = :id")
_LOG = text(
    "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id, nda_acceptance_id,"
    " nda_template_version, render_kind, fingerprint_seed) VALUES (:id, :proposal, :version, :owner, :viewer, :org,"
    " :nda, :nda_version, 'html', :seed) RETURNING started_at"
)


async def render(db: AsyncSession, settings: Settings, wrapper: KeyWrapper, live: LiveSession, access: Access) -> str:
    """The marked HTML page of ``access``'s version for ``live``'s user (see the module docstring)."""
    target = access.target
    document = await tier2.load(db, wrapper, target.proposal_id, target.version_id)
    if document is None:
        raise not_found("This version has no full proposal.")
    owner_name = target.owner_handle
    if access.reveals_owner:
        owner_name = (await db.execute(_OWNER_NAME, {"id": target.owner_id})).scalar_one()
    viewer_name = live.user.display_name
    if access.owner:
        view_id, org_name, viewed_at = None, None, clock.utcnow()
        await audit(
            db,
            OWNER_READ,
            actor_user_id=live.user.id,
            subject_type="proposal",
            subject_id=target.proposal_id,
            payload={"version_ids": [str(target.version_id)], "by_owner": True, "render": RenderKind.HTML.value},
        )
    else:
        view_id = uuid7()
        org_name = (await db.execute(_ORG_NAME, {"id": access.org_id})).scalar_one()
        viewed_at = (
            await db.execute(
                _LOG,
                {
                    "id": view_id,
                    "proposal": target.proposal_id,
                    "version": target.version_id,
                    "owner": target.owner_id,
                    "viewer": live.user.id,
                    "org": access.org_id,
                    "nda": access.nda_acceptance_id,
                    "nda_version": access.nda_template_version,
                    "seed": os.urandom(16),  # for the Release 2 invisible marks
                },
            )
        ).scalar_one()
        await audit(
            db,
            VIEWED,
            actor_user_id=live.user.id,
            org_id=access.org_id,
            subject_type="proposal_version",
            subject_id=target.version_id,
            payload={
                "proposal_id": str(target.proposal_id),
                "view_id": str(view_id),
                "render_kind": RenderKind.HTML.value,
                "nda_template_version": access.nda_template_version,
            },
        )
    html = pages.render_document(
        title=target.title,
        document=document.body,
        owner=pages.OwnerMark(
            name=owner_name,
            cert_id=target.cert_id,
            registered_at=target.registered_at,
            verify_url=verify_url(settings.public_base_url, target.cert_id),
        ),
        viewer=pages.ViewerMark(name=viewer_name, org_name=org_name, view_id=view_id, viewed_at=viewed_at),
    )
    await db.commit()
    return html


# --- "Who has seen this" ---------------------------------------------------------------------------------------------


class ViewOrg(BaseModel):
    id: UUID
    name: str | None  # None when the organisation is no longer listed


class ViewOut(BaseModel):
    view_id: UUID
    viewed_at: datetime
    org: ViewOrg
    viewer_name: str
    version_no: int
    render_kind: RenderKind
    duration: ViewDuration | None
    nda_version: str | None


class ProposalViews(BaseModel):
    """Who opened your proposal's full version, newest first (at most 500)."""

    items: list[ViewOut]
    note: str


_OWNED = text("SELECT 1 FROM proposals WHERE id = :proposal AND owner_id = :owner")
_VIEWS = text(
    "SELECT d.id, d.started_at, d.org_id, o.legal_name, u.display_name, v.version_no, d.render_kind,"
    " d.duration_bucket, d.nda_template_version FROM document_views d"
    " JOIN proposal_versions v ON v.id = d.version_id JOIN users u ON u.id = d.viewer_user_id"
    " LEFT JOIN organizations o ON o.id = d.org_id"
    " WHERE d.proposal_id = :proposal AND d.owner_id = :owner ORDER BY d.started_at DESC, d.id DESC LIMIT :limit"
)


async def who_has_seen(db: AsyncSession, *, owner_id: UUID, proposal_id: UUID) -> ProposalViews:
    """The owner's access log of one proposal; 404 for anyone else's."""
    if (await db.execute(_OWNED, {"proposal": proposal_id, "owner": owner_id})).first() is None:
        raise not_found("No proposal of yours has this id.")
    rows = (await db.execute(_VIEWS, {"proposal": proposal_id, "owner": owner_id, "limit": MAX_VIEWS})).all()
    return ProposalViews(
        items=[
            ViewOut(
                view_id=r.id,
                viewed_at=r.started_at,
                org=ViewOrg(id=r.org_id, name=r.legal_name),
                viewer_name=r.display_name,
                version_no=r.version_no,
                render_kind=r.render_kind,
                duration=r.duration_bucket,
                nda_version=r.nda_template_version,
            )
            for r in rows
        ],
        note=PANEL_NOTE,
    )
