"""A Tier-2 scene for the T2.5 tests (REQ-REPO-01, REQ-PROV-03, REQ-SEC-01; docs/spec/06 6.1).

``build_scene`` publishes a proposal through the API as a D1 developer, then (as the owner role) sets up an E2
organisation with a verified domain whose reviewer may open that proposal's Tier 2: the reviewer's address at the
verified domain is confirmed and TOTP is enrolled; a signatory accepted the current Master Enterprise Terms; the
developer tagged the organisation (a ``delivered`` tag) and ``grant_on_tag`` applied the default policy; the reviewer
accepted the current Evaluation NDA for the proposal. ``broken`` removes exactly one condition (``BREAKS``); the
reviewer's client has ``FEATURE_TIER2_ENABLED`` on unless ``enabled=False``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Final
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.proposals import grants
from tests.integration.api import make_client, sign_in_as
from tests.integration.proposals.helpers import Developers, ProposalWorld, published, user_of

ENDED: Final = {
    "engagement_withdrawn": ("WITHDRAWN", None),
    "engagement_declined": ("DECLINED", "NOT_PRIORITY"),
    "engagement_terminated": ("TERMINATED", None),
}
# Each breaks one condition; the expected (status, code) of the render. "none" and "met_by_the_approved_claimant"
# break nothing (the second meets the terms condition the other way: the reviewer cannot see the claim).
BREAKS: Final = {
    "none": (200, None),
    "met_by_the_approved_claimant": (200, None),
    "feature_disabled": (403, "tier2_disabled"),
    "proposal_hidden": (404, "not_found"),
    "proposal_held": (404, "not_found"),
    "not_member": (404, "not_found"),
    "org_not_e2": (403, "org_not_e2"),
    "org_suspended": (403, "org_suspended"),
    "role_viewer": (403, "role_not_permitted"),
    "email_unverified": (403, "email_unverified"),
    "off_domain": (403, "domain_mismatch"),
    "no_totp": (403, "mfa_enrolment_required"),
    "stale_step_up": (403, "step_up_required"),
    "no_master_terms": (403, "master_terms_required"),
    "met_by_a_non_signatory": (403, "master_terms_required"),
    "met_superseded": (403, "master_terms_required"),
    "no_grant": (403, "grant_required"),
    "grant_requested": (403, "grant_required"),
    "grant_revoked": (403, "grant_revoked"),
    "engagement_withdrawn": (403, "engagement_ended"),
    "engagement_declined": (403, "engagement_ended"),
    "engagement_terminated": (403, "engagement_ended"),
    "no_nda": (403, "nda_required"),
    "nda_superseded": (403, "nda_required"),
    "another_org": (403, "grant_required"),
}
# The condition the audit event names when it differs from the response code (404s do not say why).
AUDITED: Final = {
    "proposal_hidden": "proposal_unavailable",
    "proposal_held": "proposal_unavailable",
    "not_member": "not_member",
}


@dataclass(frozen=True, slots=True)
class Scene:
    owner: httpx.AsyncClient
    viewer: httpx.AsyncClient
    owner_id: UUID
    owner_handle: str
    proposal_id: UUID
    version_id: UUID
    cert_id: str
    org_id: UUID  # the organisation the reviewer asks through (another one for "another_org")
    granted_org_id: UUID
    org_name: str
    viewer_id: UUID
    viewer_name: str
    grant_id: UUID | None

    def path(self, leaf: str, org_id: UUID | None = None) -> str:
        """``/api/orgs/{org}/proposals/{proposal}/{leaf}`` (``tier2`` or ``nda``)."""
        return f"/api/orgs/{org_id or self.org_id}/proposals/{self.proposal_id}/{leaf}"


async def run(conn: AsyncConnection, sql: str, **params: object) -> None:
    await conn.execute(text(sql), params)


async def add_user(conn: AsyncConnection, email: str, name: str) -> UUID:
    user = uuid7()
    await run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
        " VALUES (:id, :email, :name, now(), now())",
        id=user,
        email=email,
        name=name,
    )
    return user


async def add_member(conn: AsyncConnection, org: UUID, user: UUID, roles: str) -> None:
    await run(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS org_role[]))",
        id=uuid7(),
        org=org,
        user=user,
        roles=roles,
    )


async def new_template(conn: AsyncConnection, kind: str) -> UUID:
    """A new, so current, version of the Master Enterprise Terms (``master_enterprise_terms``) or of the Evaluation
    NDA (``evaluation_nda``: its legal body and its ``nda_templates`` row; the NDA template's id is returned)."""
    legal = uuid7()
    await run(
        conn,
        "INSERT INTO legal_templates (id, kind, version, body, sha256) VALUES (:id, CAST(:kind AS legal_template_kind),"
        " :version, :body, sha256(convert_to(:body, 'UTF8')))",
        id=legal,
        kind=kind,
        version=f"t-{legal.hex[-12:]}",
        body=f"DRAFT\n\n[[LEGAL-PLACEHOLDER:{kind}-{legal.hex}]]\n",
    )
    if kind != "evaluation_nda":
        return legal
    template = uuid7()
    await run(
        conn,
        "INSERT INTO nda_templates (id, kind, version, legal_template_id, sha256)"
        " SELECT :id, 'evaluation', :version, id, sha256 FROM legal_templates WHERE id = :legal",
        id=template,
        version=f"e-{template.hex[-12:]}",
        legal=legal,
    )
    return template


async def accept_terms(conn: AsyncConnection, org: UUID, user: UUID, terms: UUID) -> None:
    await run(
        conn,
        "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
        " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE id = :terms",
        id=uuid7(),
        org=org,
        user=user,
        terms=terms,
    )


async def accept_nda(conn: AsyncConnection, user: UUID, org: UUID, proposal: UUID, template: UUID) -> None:
    await run(
        conn,
        "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
        " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
        " WHERE id = :template",
        id=uuid7(),
        user=user,
        org=org,
        proposal=proposal,
        template=template,
    )


async def add_e2_org(conn: AsyncConnection, name: str, domain: str, terms: UUID, acceptor_roles: str) -> UUID:
    """An E2 organisation on ``domain`` whose member with ``acceptor_roles`` accepted ``terms``."""
    org = uuid7()
    await run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain, e2_verified_at)"
        " VALUES (:id, 'company', :name, :slug, 'seed', 'e2', :domain, now())",
        id=org,
        name=name,
        slug=f"t2-{org.hex[-12:]}",
        domain=domain,
    )
    acceptor = await add_user(conn, f"acceptor-{org.hex[-12:]}@{domain}", "Sam Signatory")
    await add_member(conn, org, acceptor, acceptor_roles)
    if acceptor_roles == "{owner,admin}":  # the organisation's approved E2 claimant
        await run(
            conn,
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :user, :domain, :email, 'e2', 'approved')",
            id=uuid7(),
            org=org,
            user=acceptor,
            domain=domain,
            email=f"acceptor-{org.hex[-12:]}@{domain}",
        )
    await accept_terms(conn, org, acceptor, terms)
    return org


async def apply_grant(app_engine: AsyncEngine, owner_id: UUID, proposal_id: UUID, org_id: UUID) -> UUID | None:
    """What the Pitch flow does after delivering a tag: the owner's session calls ``grant_on_tag``."""
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=owner_id)
        grant_id = await grants.grant_on_tag(db, owner_id=owner_id, proposal_id=proposal_id, org_id=org_id)
        await db.commit()
    return grant_id


async def deliver_tag(owner_engine: AsyncEngine, proposal_id: UUID, org_id: UUID, owner_id: UUID) -> None:
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
            " VALUES (:id, :p, :org, :dev, 'delivered')",
            id=uuid7(),
            p=proposal_id,
            org=org_id,
            dev=owner_id,
        )


async def viewer_client(
    stack: AsyncExitStack, app_engine: AsyncEngine, owner: httpx.AsyncClient, user_id: UUID, *, enabled: bool = True
) -> httpx.AsyncClient:
    """A signed-in client (second factor just confirmed) sharing the owner's Tier-2 key wrapper."""
    settings = get_settings().model_copy(update={"feature_tier2_enabled": enabled})
    client = await stack.enter_async_context(make_client(app_engine, settings))
    client.app.state.key_wrapper = owner.app.state.key_wrapper  # type: ignore[attr-defined]
    await sign_in_as(client, app_engine, user_id, mfa_verified=True)
    client.user_id = user_id  # type: ignore[attr-defined]
    return client


async def build_scene(
    stack: AsyncExitStack,
    developers: Developers,
    world: ProposalWorld,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    broken: str = "none",
) -> Scene:
    assert broken in BREAKS, broken
    owner = await developers()
    owner_id = user_of(owner)
    publication = await published(owner, world)
    proposal_id, version_id = UUID(publication["proposal_id"]), UUID(publication["version_id"])
    tag = uuid7().hex[-10:]
    domain = f"buyer-{tag}.example.test"
    org_name = f"Buyer {tag} Limited"
    viewer_name = f"Rita Reviewer {tag}"
    async with owner_engine.begin() as conn:
        terms = await new_template(conn, "master_enterprise_terms")
        nda = await new_template(conn, "evaluation_nda")
        acceptor_roles = {
            "met_by_the_approved_claimant": "{owner,admin}",
            "met_by_a_non_signatory": "{reviewer}",
        }.get(broken, "{signatory}")
        org = await add_e2_org(conn, org_name, domain, terms, acceptor_roles)
        if broken == "no_master_terms":
            await new_template(conn, "master_enterprise_terms")  # nobody accepted the current version
        viewer = await add_user(conn, f"rita-{tag}@{domain}", viewer_name)
        await add_member(conn, org, viewer, "{reviewer}")
        if broken != "no_nda":
            await accept_nda(conn, viewer, org, proposal_id, nda)
        asked = org
        if broken == "another_org":  # everything but a grant, under a second organisation of the reviewer's
            asked = await add_e2_org(conn, f"Other {tag} Limited", domain, terms, "{signatory}")
            await add_member(conn, asked, viewer, "{reviewer}")
            await accept_nda(conn, viewer, asked, proposal_id, nda)
        if broken == "grant_requested":
            await run(
                conn,
                "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, requested_by)"
                " VALUES (:id, :p, :org, :owner, 2, 'requested', 'org_interest', :viewer)",
                id=uuid7(),
                p=proposal_id,
                org=org,
                owner=owner_id,
                viewer=viewer,
            )
    grant_id = None
    if broken not in ("no_grant", "grant_requested"):
        await deliver_tag(owner_engine, proposal_id, org, owner_id)
        grant_id = await apply_grant(app_engine, owner_id, proposal_id, org)
    client = await viewer_client(stack, app_engine, owner, viewer, enabled=broken != "feature_disabled")
    await break_after(owner_engine, broken, proposal_id=proposal_id, org=org, viewer=viewer, owner_id=owner_id)
    handle = f"dev-{owner_id.hex[-12:]}"
    return Scene(
        owner=owner,
        viewer=client,
        owner_id=owner_id,
        owner_handle=handle,
        proposal_id=proposal_id,
        version_id=version_id,
        cert_id=publication["cert_id"],
        org_id=asked,
        granted_org_id=org,
        org_name=org_name,
        viewer_id=viewer,
        viewer_name=viewer_name,
        grant_id=grant_id,
    )


BREAK_SQL: Final = {
    "proposal_hidden": "UPDATE proposals SET status = 'hidden', hidden_at = now() WHERE id = :p",
    "proposal_held": "UPDATE proposals SET moderation_state = 'held' WHERE id = :p",
    "not_member": "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :viewer",
    "role_viewer": "UPDATE memberships SET roles = '{viewer}' WHERE org_id = :org AND user_id = :viewer",
    "org_not_e2": "UPDATE organizations SET verification = 'e1' WHERE id = :org",
    "org_suspended": "UPDATE organizations SET suspended_at = now() WHERE id = :org",
    "email_unverified": "UPDATE users SET email_verified_at = NULL WHERE id = :viewer",
    "off_domain": "UPDATE users SET email = 'rita-' || id || '@elsewhere.example.test' WHERE id = :viewer",
    "no_totp": "UPDATE users SET totp_enabled_at = NULL WHERE id = :viewer",
    "stale_step_up": "UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :viewer",
    "grant_revoked": "UPDATE disclosure_grants SET status = 'revoked', revoked_at = now(), revoked_by = :owner"
    " WHERE proposal_id = :p AND org_id = :org",
}


async def break_after(
    owner_engine: AsyncEngine, broken: str, *, proposal_id: UUID, org: UUID, viewer: UUID, owner_id: UUID
) -> None:
    params = {"p": proposal_id, "org": org, "viewer": viewer, "owner": owner_id}
    async with owner_engine.begin() as conn:
        if broken in BREAK_SQL:
            await run(conn, BREAK_SQL[broken], **params)
        if broken == "met_superseded":
            await new_template(conn, "master_enterprise_terms")
        if broken == "nda_superseded":
            await new_template(conn, "evaluation_nda")
        if broken in ENDED:
            await add_engagement(conn, proposal_id, org, owner_id, *ENDED[broken])


async def add_engagement(
    conn: AsyncConnection, proposal_id: UUID, org: UUID, owner_id: UUID, state: str, reason: str | None = None
) -> None:
    await run(
        conn,
        "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state, end_reason)"
        " SELECT :id, p.id, :org, :dev, p.current_version_id, 'tagged', CAST(:state AS engagement_state),"
        " CAST(:reason AS engagement_end_reason) FROM proposals p WHERE p.id = :p",
        id=uuid7(),
        p=proposal_id,
        org=org,
        dev=owner_id,
        state=state,
        reason=reason,
    )


SceneFactory = Callable[..., Awaitable[Scene]]


@pytest.fixture
async def scenes(
    developers: Developers, proposal_world: ProposalWorld, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> AsyncIterator[SceneFactory]:
    """``await scenes(broken="none")``: a Tier-2 scene (see the module docstring)."""
    async with AsyncExitStack() as stack:

        async def make(broken: str = "none") -> Scene:
            return await build_scene(stack, developers, proposal_world, app_engine, owner_engine, broken)

        yield make
