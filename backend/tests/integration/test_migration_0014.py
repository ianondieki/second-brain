"""Revision 0014 (REQ-PROV-06; docs/spec/06 6.4 pt 5): the evidence clock. A Tier-2 view, and the Master Enterprise
Terms and Evaluation NDA acceptances before it, are stamped on the shared clock (``app_clock_now()``); an attestation
stays on the database clock of the registration it is made in.

- With the shared clock moved past the ten business days a window lasts, a new Tier-2 view's ``started_at`` is the
  shared clock's instant (not the database clock's), ``app_prior_knowledge_window`` opens on that Nairobi day and closes
  ten Kenyan business days later, and a declaration on the moved clock is accepted, its window the view's. Under
  revision 0013 the view fell on the database clock's day, whose window had closed before the moved "today".
- The same through the API: after the clock moved, the organisation's tracker offers the declaration right after its
  first view (``can_declare``) and the signatory's declaration is accepted (201), as
  ``frontend/e2e/declaration.spec.ts`` expects on a moved stack.
- The acceptances, inserted as bridge_app with a backdated time, carry the shared clock's instant; an attestation the
  developer makes carries ``now()``, its version's ``registered_at``.

The round trip (0014 replaces one function body and its downgrade restores revision 0002's byte for byte) and the
unmoved evidence times are in ``test_migrations.py``. The database-level tests run in one rolled-back transaction
(``tracker.as_app``) and reuse revision 0013's world; the API test commits its own world and puts the clock back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.calendar import add_business_days, local_date
from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t
from tests.integration.engagements.api_world import (
    build,
    clients,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
)
from tests.integration.engagements.test_prior_knowledge import body, org_window, path, tier2_view
from tests.integration.test_migration_0013 import DECLARE, WINDOW, declaration, holidays, move_clock, scene, view

# Far enough past ten Kenyan business days (14 calendar days, more with holidays) that a window opened on the database
# clock's day has closed by the moved day: the residual revision 0013 kept.
MOVED_DAYS = 30
SETTINGS = deals_on()
BACKDATED = datetime.now(UTC) - timedelta(days=30)
DB_TODAY = "SELECT (now() AT TIME ZONE 'Africa/Nairobi')::date"
ON_THE_MOVED_CLOCK = "{column} >= now() + make_interval(days => :d) AND {column} <= app_clock_now()"


async def test_a_view_on_the_moved_clock_opens_a_window_the_organisation_declares_in(owner_engine: AsyncEngine) -> None:
    """Given the shared clock MOVED_DAYS ahead of the database clock, When a member of the organisation views the
    proposal's Tier 2, Then the view's start is the shared clock's instant, the window opens on the moved Nairobi day
    and closes ten Kenyan business days later, and the signatory's declaration on the moved clock is accepted with that
    window and a time on the moved day."""
    async with t.as_app(owner_engine) as conn:
        p, engagement = await scene(conn)
        await move_clock(conn, MOVED_DAYS)
        database_today = await t.run(conn, DB_TODAY)
        moved_today = await t.run(conn, "SELECT app_nairobi_today()")
        assert moved_today == database_today + timedelta(days=MOVED_DAYS)
        known = await holidays(conn)
        assert add_business_days(database_today, 10, known) < moved_today  # where 0013's window would have closed

        first = await view(conn, p, p.reviewer)
        moved_start, clock_after = (
            await conn.execute(sa.text("SELECT now() + make_interval(days => :d), app_clock_now()"), {"d": MOVED_DAYS})
        ).one()
        assert moved_start <= first <= clock_after  # the shared clock's instant at the insert
        assert local_date(first) == moved_today
        closes = add_business_days(moved_today, 10, known)

        await t.act(conn, p.signatory, p.org)
        assert (await conn.execute(sa.text(WINDOW), {"e": engagement})).one() == (first, closes)
        params = declaration(p, engagement, p.signatory, dated=moved_today)  # the first view's own day: the boundary
        await t.run(conn, DECLARE, **params)
        row = (
            await conn.execute(
                sa.text(
                    "SELECT first_tier2_view_at, window_closes_on, declared_at, evidence_dated_on"
                    " FROM prior_knowledge_declarations WHERE id = :id"
                ),
                {"id": params["id"]},
            )
        ).one()
        assert (row.first_tier2_view_at, row.window_closes_on, row.evidence_dated_on) == (first, closes, moved_today)
        assert row.declared_at >= first
        assert local_date(row.declared_at) == moved_today


async def test_after_the_clock_moved_the_tracker_offers_the_declaration_right_after_the_first_view(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The demo's story through the API: the shared clock moves MOVED_DAYS on, a new engagement is opened and the
    organisation views its Tier 2; its tracker then offers the declaration (the window closes ten business days after
    the moved day) and the signatory's declaration is accepted, its first view and time on the moved day."""
    world = await build(owner_engine)
    async with moved_clock(owner_engine) as advance:
        await advance(MOVED_DAYS)
        today = await db_today(owner_engine)
        engagement = await open_engagement(app_engine, world)
        assert await tier2_view(owner_engine, world) == today
        closes = add_business_days(today, 10, await holidays_of(owner_engine))
        async with clients(app_engine, SETTINGS, world.signatory) as (signatory,):
            window = await org_window(signatory, engagement)
            assert (window["window_closes_on"], window["can_declare"]) == (str(closes), True)
            declared = await signatory.post(path(world, engagement), json=body(today))
            assert declared.status_code == 201, declared.text
            out = declared.json()
            assert (out["first_tier2_view_at"], out["window_closes_on"]) == (window["first_tier2_view_at"], str(closes))
            assert local_date(datetime.fromisoformat(out["declared_at"])) == today
            assert local_date(datetime.fromisoformat(out["first_tier2_view_at"])) == today


async def test_the_acceptances_are_on_the_shared_clock_and_an_attestation_on_its_registrations(
    owner_engine: AsyncEngine,
) -> None:
    """Given the shared clock MOVED_DAYS on, When the organisation's signatory accepts the Master Enterprise Terms, its
    reviewer the Evaluation NDA and the developer makes an attestation, each as bridge_app sending a backdated time,
    Then both acceptances carry the shared clock's instant at the insert, and the attestation the database clock's
    now(), its version's registered_at (the registration's transaction)."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        met_template, nda_template = await w.add_templates(conn, uuid7().hex[-12:])
        await move_clock(conn, MOVED_DAYS)
        terms, nda, attestation = uuid7(), uuid7(), uuid7()

        await t.act(conn, p.signatory, p.org)
        await t.run(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256, accepted_at)"
            " SELECT :id, :org, :u, id, sha256, :at FROM legal_templates WHERE id = :template",
            id=terms,
            org=p.org,
            u=p.signatory,
            template=met_template,
            at=BACKDATED,
        )
        await t.act(conn, p.reviewer, p.org)
        await t.run(
            conn,
            "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
            " logging_notice_version, accepted_at) SELECT :id, :u, :org, :p, id, sha256, 'v1', :at"
            " FROM nda_templates WHERE id = :template",
            id=nda,
            u=p.reviewer,
            org=p.org,
            p=p.proposal,
            template=nda_template,
            at=BACKDATED,
        )
        await t.act(conn, p.developer)
        await t.run(
            conn,
            "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
            " no_third_party_confidential, text_version, text_sha256, created_at)"
            " VALUES (:id, :u, :v, true, true, true, 'v1', :h, :at)",
            id=attestation,
            u=p.developer,
            v=p.version,
            h=bytes(32),
            at=BACKDATED,
        )

        await t.as_owner(conn)
        on_the_clock = ON_THE_MOVED_CLOCK.format(column="accepted_at")
        for table, row_id in (("legal_acceptances", terms), ("nda_acceptances", nda)):
            stamped = await t.run(conn, f"SELECT {on_the_clock} FROM {table} WHERE id = :id", id=row_id, d=MOVED_DAYS)
            assert stamped is True, f"{table}.accepted_at is not the shared clock's"
        made, registered, database_now = (
            await conn.execute(
                sa.text(
                    "SELECT a.created_at, v.registered_at, now() FROM attestations a"
                    " JOIN proposal_versions v ON v.id = a.version_id WHERE a.id = :id"
                ),
                {"id": attestation},
            )
        ).one()
        assert made == registered == database_now  # the registration's clock, not the moved one
