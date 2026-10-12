"""REQ-PROV-06 (P27 track D; docs/spec/06 6.4 pt 5): "within 10 business days of first Tier-2 access an org may declare
existing similar work by submitting the hash of dated internal evidence; shown to the owner; declarations are not
recorded on the platform after this window".

Acceptance 4, on the test clock: after Telco A's first Tier-2 view its signatory declares a hash within 10 business
days (201; the 10th business day included); the developer gets N31 (in-app and the status email: the organisation and
the idea's title, never the evidence's title or hash) and sees the declaration (organisation, hash, title, date) on
the tracker, and another developer does not; the 11th business day refuses ``declaration_window_closed`` with the
spec's sentence and the organisation's tracker no longer offers it; before any view it refuses
``no_tier2_access_yet``; a second declaration refuses 409; the row cannot be updated or deleted (its triggers); the
engagement's event chain verifies with the ``prior_knowledge_declared`` event in it (ids and the hash only).

A Tier-2 view and the declaration that follows it happen in the same clock epoch: the view is stamped by the database's
clock and the window closes on the shared clock, so the clock moves only after the views (the boundary tests)."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import chain, prior_knowledge
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.notify import DECLARED_TITLE, N31_KIND
from bridge.engagements.prior_knowledge import COMMAND, WINDOW_CLOSED, Window
from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    PROPOSAL_TITLE,
    World,
    build,
    business_days_later,
    clients,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
    run_notifications,
    seats,
)

SETTINGS = deals_on()
EVIDENCE = hashlib.sha256(b"Telco A internal design note, rural backhaul, March 2025").hexdigest()
TITLE = "Rural backhaul design note (internal, v3)"
SPEC_SENTENCE = "declarations are not recorded on the platform after this window"


def path(world: World, engagement: UUID) -> str:
    return f"/api/orgs/{world.org}/engagements/{engagement}/prior-knowledge"


def body(dated_on: date, *, digest: str = EVIDENCE, title: str = TITLE) -> dict[str, str]:
    return {"evidence_sha256_hex": digest, "evidence_title": title, "evidence_dated_on": str(dated_on)}


def code(response: httpx.Response) -> tuple[int, str | None]:
    detail = response.json().get("detail")
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def declarations(engine: AsyncEngine, engagement: UUID) -> list[str]:
    """The evidence titles of the engagement's declarations, as the owner reads them."""
    found = await rows(
        engine, "SELECT evidence_title FROM prior_knowledge_declarations WHERE engagement_id = :e", e=engagement
    )
    return [str(row.evidence_title) for row in found]


async def tier2_view(owner_engine: AsyncEngine, world: World, *, days_ago: int = 0) -> date:
    """The organisation's reviewer views the proposal's Tier 2 (the access log); returns the view's Nairobi day.
    ``days_ago`` backdates it in calendar days (the owner's edit of a stamped time; the window stays open)."""
    async with owner_engine.begin() as conn:
        view = uuid7()
        await conn.execute(
            text(
                "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id,"
                " render_kind, fingerprint_seed) VALUES (:id, :p, :v, :d, :viewer, :o, 'html', '\\x00')"
            ),
            {
                "id": view,
                "p": world.proposal,
                "v": world.version,
                "d": world.developer,
                "viewer": world.reviewer,
                "o": world.org,
            },
        )
        if days_ago:
            await conn.execute(
                text("UPDATE document_views SET started_at = started_at - make_interval(days => :n) WHERE id = :id"),
                {"n": days_ago, "id": view},
            )
        started = await conn.execute(text("SELECT started_at FROM document_views WHERE id = :id"), {"id": view})
        return local_date(started.scalar_one())


async def org_window(client: httpx.AsyncClient, engagement: UUID) -> dict[str, Any]:
    detail = await client.get(f"/api/engagements/{engagement}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["my_party"] == "org"
    window: dict[str, Any] = detail.json()["prior_knowledge"]
    return window


async def test_a_signatory_declares_inside_the_window_and_the_owner_is_told(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    elsewhere = await open_engagement(app_engine, other)
    viewed_on = await tier2_view(owner_engine, world)
    closes_on = add_business_days(viewed_on, 10, await holidays_of(owner_engine))
    today = await db_today(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s:
        window = await org_window(s.signatory, engagement)
        assert window["window_closes_on"] == str(closes_on)
        assert window["first_tier2_view_at"] is not None
        assert (window["declared_at"], window["can_declare"]) == (None, True)
        assert (await org_window(s.reviewer, engagement))["can_declare"] is False  # a reviewer does not declare
        assert (await org_window(s.owner, engagement))["can_declare"] is True
        dev_before = (await s.dev.get(f"/api/engagements/{engagement}")).json()
        assert dev_before["prior_knowledge"] is None

        declared = await s.signatory.post(
            path(world, engagement), json=body(today - timedelta(days=30), digest=EVIDENCE.upper())
        )
        assert declared.status_code == 201, declared.text
        out = declared.json()
        assert out["evidence_sha256_hex"] == EVIDENCE  # lower-case hex
        assert (out["evidence_title"], out["evidence_dated_on"]) == (TITLE, str(today - timedelta(days=30)))
        assert (out["window_closes_on"], out["first_tier2_view_at"]) == (str(closes_on), window["first_tier2_view_at"])

        # once per engagement
        again = await s.owner.post(path(world, engagement), json=body(today))
        assert code(again) == (409, "already_declared")
        after = await org_window(s.signatory, engagement)
        assert (after["declared_at"], after["can_declare"]) == (out["declared_at"], False)

        # the owner sees it on their tracker; the History's chain verifies with the event in it
        mine = (await s.dev.get(f"/api/engagements/{engagement}")).json()
        assert mine["prior_knowledge"] == {
            "org_name": world.org_name,
            "declared_at": out["declared_at"],
            "evidence_sha256_hex": EVIDENCE,
            "evidence_title": TITLE,
            "evidence_dated_on": str(today - timedelta(days=30)),
        }
        assert mine["state"] == "SUBMITTED"  # no state change
        history = (await s.dev.get(f"/api/engagements/{engagement}/history")).json()
        assert history["chain_verified"] is True
        last = history["events"][-1]
        assert (last["command"], last["from_state"], last["to_state"]) == (COMMAND, "SUBMITTED", "SUBMITTED")
        assert last["actor_role"] == "signatory"
        assert last["payload"] == {"declaration_id": out["id"], "org_id": str(world.org), "evidence_sha256": EVIDENCE}

    # another developer reads none of it
    async with clients(app_engine, SETTINGS, other.developer, world.outsider) as (other_dev, outsider):
        assert (await other_dev.get(f"/api/engagements/{engagement}")).status_code == 404
        assert (await other_dev.get(f"/api/engagements/{elsewhere}")).json()["prior_knowledge"] is None
        assert (await outsider.get(f"/api/engagements/{engagement}")).status_code == 404

    async with owner_engine.connect() as conn:
        assert await chain.verify_chain(conn, engagement) == []
    [row] = await rows(
        owner_engine,
        "SELECT declared_by, evidence_sha256, version_id, window_closes_on FROM prior_knowledge_declarations"
        " WHERE engagement_id = :e",
        e=engagement,
    )
    assert (row.declared_by, bytes(row.evidence_sha256).hex(), row.version_id) == (
        world.signatory,
        EVIDENCE,
        world.version,
    )
    [audit] = await rows(
        owner_engine,
        "SELECT org_id, payload FROM audit_events WHERE action = 'engagement.prior_knowledge_declared'"
        " AND subject_id = :e",
        e=engagement,
    )
    assert audit.org_id == world.org
    assert audit.payload == {"engagement_id": str(engagement), "declaration_id": out["id"]}

    # N31: in-app and the status email to the owner, naming the organisation and the idea, never the evidence
    provider = FakeEmailProvider()
    assert await run_notifications(owner_engine, app_engine, engagement, provider) == 1
    [notice] = await rows(
        owner_engine, "SELECT kind, title, body, link FROM in_app_notifications WHERE user_id = :u", u=world.developer
    )
    assert (notice.kind, notice.title, notice.link) == (N31_KIND, DECLARED_TITLE, f"/dev/engagements/{engagement}")
    assert world.org_name in notice.body
    assert PROPOSAL_TITLE in notice.body
    [email] = provider.outbox
    assert email.to == world.developer_email
    assert email.subject == f'{DECLARED_TITLE}: "{PROPOSAL_TITLE}"'
    for content in (notice.body, email.subject, email.text, email.html or ""):
        assert TITLE not in content
        assert EVIDENCE not in content.lower()
    assert world.org_name in email.text
    await run_notifications(owner_engine, app_engine, engagement, provider)
    assert len(provider.outbox) == 1  # once


async def test_n31_is_sent_whatever_the_owners_email_preferences(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """REQUIREMENTS.md §5: N31 is not mutable (a provenance record the owner must see)."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    await tier2_view(owner_engine, world)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO notification_preferences (user_id, kind, channel, enabled) VALUES (:u, :k, 'email', false)"
            ),
            {"u": world.developer, "k": N31_KIND},
        )
    async with clients(app_engine, SETTINGS, world.signatory) as (signatory,):
        response = await signatory.post(path(world, engagement), json=body(await db_today(owner_engine)))
        assert response.status_code == 201, response.text
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    assert len(provider.outbox) == 1


async def test_before_any_tier2_view_it_refuses_and_the_window_is_not_open(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with clients(app_engine, SETTINGS, world.signatory) as (signatory,):
        window = await org_window(signatory, engagement)
        assert window == {
            "first_tier2_view_at": None,
            "window_closes_on": None,
            "declared_at": None,
            "can_declare": False,
        }
        refused = await signatory.post(path(world, engagement), json=body(await db_today(owner_engine)))
        assert code(refused) == (403, "no_tier2_access_yet")
    async with create_session_factory(app_engine)() as db:  # a reader of no engagement gets no window
        await bind_tenant(db, user_id=world.signatory, org_id=world.org)
        assert await prior_knowledge.window(db, uuid7()) == Window(None, None)
    assert await declarations(owner_engine, engagement) == []


async def test_the_tenth_business_day_is_inside_and_the_eleventh_refuses_with_the_specs_sentence(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    late, edge = await build(owner_engine), await build(owner_engine)
    late_engagement = await open_engagement(app_engine, late)
    edge_engagement = await open_engagement(app_engine, edge)
    viewed_on = await tier2_view(owner_engine, late)
    assert await tier2_view(owner_engine, edge) == viewed_on
    closes_on = add_business_days(viewed_on, 10, await holidays_of(owner_engine))
    async with moved_clock(owner_engine) as advance:
        assert await business_days_later(owner_engine, advance, 10) == closes_on
        async with clients(app_engine, SETTINGS, edge.signatory) as (signatory,):
            assert (await org_window(signatory, edge_engagement))["can_declare"] is True
            on_the_day = await signatory.post(path(edge, edge_engagement), json=body(viewed_on))
            assert on_the_day.status_code == 201, on_the_day.text
        assert await business_days_later(owner_engine, advance, 1) > closes_on
        async with clients(app_engine, SETTINGS, late.signatory) as (signatory,):
            window = await org_window(signatory, late_engagement)
            assert (window["window_closes_on"], window["can_declare"]) == (str(closes_on), False)
            refused = await signatory.post(path(late, late_engagement), json=body(viewed_on))
            assert code(refused) == (403, "declaration_window_closed")
            detail = refused.json()["detail"]
            assert detail["message"] == WINDOW_CLOSED
            assert SPEC_SENTENCE in detail["message"].lower()
            assert detail["window_closed_on"] == str(closes_on)
    assert await declarations(owner_engine, late_engagement) == []


async def test_who_may_declare_and_what(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    viewed_on = await tier2_view(owner_engine, world, days_ago=3)  # three calendar days ago: the window is open
    today = await db_today(owner_engine)
    url = path(world, engagement)
    async with seats(app_engine, SETTINGS, world) as s:
        for seat in (s.reviewer, s.finance):
            assert code(await seat.post(url, json=body(viewed_on))) == (403, "role_not_allowed")
        async with clients(app_engine, SETTINGS, world.viewer, other.signatory) as (viewer, stranger):
            assert code(await viewer.post(url, json=body(viewed_on))) == (403, "role_not_allowed")
            assert (await stranger.post(url, json=body(viewed_on))).status_code == 404  # not a member
            own_org = f"/api/orgs/{other.org}/engagements/{engagement}/prior-knowledge"
            assert (await stranger.post(own_org, json=body(viewed_on))).status_code == 404  # not their engagement
        for bad in (
            {"evidence_sha256_hex": EVIDENCE[:-1]},
            {"evidence_sha256_hex": "g" * 64},
            {"evidence_title": ""},
        ):
            assert (await s.signatory.post(url, json=body(viewed_on) | bad)).status_code == 422
        for title in ("two\nlines", "x" * 201, "   "):
            refused = await s.signatory.post(url, json=body(viewed_on, title=title))
            assert code(refused) == (422, "invalid_evidence_title")
        future = await s.signatory.post(url, json=body(today + timedelta(days=1)))
        assert code(future) == (422, "evidence_date_in_future")
        after_view = await s.signatory.post(url, json=body(viewed_on + timedelta(days=1)))
        assert code(after_view) == (422, "evidence_after_first_view")
        assert (await s.owner.post(url, json=body(viewed_on, title=f"  {TITLE}  "))).status_code == 201
        assert await declarations(owner_engine, engagement) == [TITLE]  # trimmed


async def test_an_ended_engagement_takes_no_declaration(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Revision 0003's chain takes no event once an engagement has ended: 409, checked before the window."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, SETTINGS, world) as s:
        lock = (await s.dev.get(f"/api/engagements/{engagement}")).json()["lock_version"]
        withdrawn = await s.dev.post(f"/api/engagements/{engagement}/withdraw", json={"lock_version": lock})
        assert withdrawn.status_code == 200, withdrawn.text
        today = await db_today(owner_engine)
        assert code(await s.signatory.post(path(world, engagement), json=body(today))) == (409, "engagement_ended")
        await tier2_view(owner_engine, world)
        assert code(await s.signatory.post(path(world, engagement), json=body(today))) == (409, "engagement_ended")
        assert (await org_window(s.signatory, engagement))["can_declare"] is False


async def test_a_declaration_is_append_only(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    await tier2_view(owner_engine, world)
    async with clients(app_engine, SETTINGS, world.signatory) as (signatory,):
        assert (
            await signatory.post(path(world, engagement), json=body(await db_today(owner_engine)))
        ).status_code == 201
    for statement in (
        "UPDATE prior_knowledge_declarations SET evidence_title = 'Changed' WHERE engagement_id = :e",
        "DELETE FROM prior_knowledge_declarations WHERE engagement_id = :e",
    ):
        with pytest.raises(DBAPIError):  # the owner too: block_mutation()
            async with owner_engine.begin() as conn:
                await conn.execute(text(statement), {"e": engagement})
        async with create_session_factory(app_engine)() as db:
            await bind_tenant(db, user_id=world.signatory, org_id=world.org)
            with pytest.raises(DBAPIError):  # the declarer (bridge_app): no grant, and the trigger
                await db.execute(text(statement), {"e": engagement})
    with pytest.raises(DBAPIError):
        async with owner_engine.begin() as conn:
            await conn.execute(text("TRUNCATE prior_knowledge_declarations"))
    assert await declarations(owner_engine, engagement) == [TITLE]
