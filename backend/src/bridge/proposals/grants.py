"""Tier-2 disclosure grants (REQ-REPO-01, REQ-BIL-03; docs/spec/06 6.1).

The prototype builds the owner's default policy only, "auto-grant to orgs I tagged": ``grant_on_tag`` is what the Pitch
flow (P4, T2.7) calls, in the owner's request and transaction, right after it inserts a ``delivered`` tag for an E2
organisation. Manual approval, the "any E2 organisation in my niche" policy, organisations' grant requests,
revocation by the owner and the unlock quota of grants on untagged proposals come after the prototype
(``REQUIREMENTS.md`` §7). A grant from a tag never counts as an unlock (``counts_as_unlock`` false).

A grant opens nothing on its own: ``can_view_tier2`` (``bridge.proposals.access``) still needs every other condition,
``FEATURE_TIER2_ENABLED`` included, so a grant created while the flag is off releases nothing until it is on.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.ids import uuid7
from bridge.models.enums import GrantSource, GrantStatus, Tier2Policy

GRANTED: Final = "tier2.grant_created"
ACTIVATED: Final = "tier2.grant_activated"
TIER2: Final = 2


class GrantError(Exception):
    """The caller broke the contract of ``grant_on_tag`` (not the owner, or no open delivered tag): a bug, not a user
    error, so it is not an ``ApiError``."""


_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_PROPOSAL = text("SELECT tier2_policy FROM proposals WHERE id = :proposal AND owner_id = :owner")
_TAG = text(
    "SELECT EXISTS (SELECT 1 FROM tags WHERE proposal_id = :proposal AND org_id = :org AND developer_id = :owner"
    " AND status = 'delivered' AND closed_at IS NULL)"
)
_LIVE = text(
    "SELECT id, status, source FROM disclosure_grants WHERE proposal_id = :proposal AND org_id = :org AND tier = :tier"
    " AND status IN ('requested', 'active')"
)
_ACTIVATE = text(
    "UPDATE disclosure_grants SET status = 'active', granted_by = :owner, granted_at = now(), updated_at = now()"
    " WHERE id = :id"
)
_INSERT = text(
    "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, counts_as_unlock,"
    " granted_by, granted_at) VALUES (:id, :proposal, :org, :owner, :tier, 'active', 'auto_tagged', false, :owner,"
    " now())"
)


async def grant_on_tag(db: AsyncSession, *, owner_id: UUID, proposal_id: UUID, org_id: UUID) -> UUID | None:
    """Apply the owner's policy to a tag just delivered to ``org_id``: the live Tier-2 grant's id, or None when the
    policy is not ``auto_tagged`` (the owner approves each organisation instead).

    Call it inside the transaction that inserted the tag, with the owner's tenant bound (``bind_tenant``); it does not
    commit. Idempotent: an active grant is returned as it is, and an organisation's pending request is activated.
    Raises ``GrantError`` when ``owner_id`` does not own the proposal or no open ``delivered`` tag of theirs names the
    organisation (only E2 organisations receive delivered tags)."""
    params = {"proposal": proposal_id, "org": org_id, "owner": owner_id, "tier": TIER2}
    await db.execute(_LOCK, {"key": f"tier2.grant:{proposal_id}:{org_id}"})
    policy = (await db.execute(_PROPOSAL, params)).scalar_one_or_none()
    if policy is None:
        raise GrantError("grant_on_tag: the proposal is not the owner's")
    if not (await db.execute(_TAG, params)).scalar_one():
        raise GrantError("grant_on_tag: no open delivered tag of the owner names this organisation")
    if policy != Tier2Policy.AUTO_TAGGED:
        return None
    live = (await db.execute(_LIVE, params)).one_or_none()
    if live is not None and live.status == GrantStatus.ACTIVE:
        return UUID(str(live.id))
    if live is not None:  # the request keeps its source (the organisation asked first)
        grant_id, action, source = UUID(str(live.id)), ACTIVATED, str(live.source)
        await db.execute(_ACTIVATE, {"id": grant_id, "owner": owner_id})
    else:
        grant_id, action, source = uuid7(), GRANTED, GrantSource.AUTO_TAGGED.value
        await db.execute(_INSERT, params | {"id": grant_id})
    await audit(
        db,
        action,
        actor_user_id=owner_id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={
            "grant_id": str(grant_id),
            "org_id": str(org_id),
            "tier": TIER2,
            "source": source,
        },
    )
    return grant_id
