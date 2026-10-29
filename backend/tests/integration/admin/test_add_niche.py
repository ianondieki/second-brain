"""``POST /api/admin/niches`` (REQ-ADM-01, REQ-DIR-01; AC-DIR-5/a, admin half): staff admin adds a niche without a
deploy through ``app_add_niche``. 201 with the niche; 409 for a taken slug; 422 for a parent that is not an active
top-level niche (or does not exist) and for a malformed body; audited as ``directory.niche_added`` with ids only.
Everyone else gets the staff dependency's answers (404 for non-staff, 403 for a moderator)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.seed.reference import seed_all
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as

NOT_FOUND = {"detail": {"code": "not_found", "message": "Not found."}}


@pytest.fixture(scope="module")
async def tag(owner_engine: AsyncEngine) -> AsyncIterator[str]:
    """The reference seed, and a tag every niche made here ends with (removed at the end)."""
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())
    tag = uuid4().hex[:8]
    yield tag
    async with owner_engine.begin() as conn:
        await conn.execute(text("DELETE FROM niches WHERE slug LIKE :mine"), {"mine": f"%-{tag}"})


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as c:
        yield c


async def _sign_in(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, staff_role: str | None
) -> UUID:
    async with owner_engine.begin() as conn:
        user_id = await w.add_user(conn, f"niche-{uuid4().hex[:10]}@example.test", "Niche", staff_role=staff_role)
    await sign_in_as(client, app_engine, user_id, mfa_verified=True)
    return user_id


async def _events(owner_engine: AsyncEngine, niche_id: str) -> list[Any]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT e.action, e.actor_kind::text AS actor_kind, e.actor_user_id, e.org_id, e.subject_type,"
                " e.subject_id, e.payload, d.event_id IS NOT NULL AS has_details"
                " FROM audit_events e LEFT JOIN event_details d ON d.event_id = e.id"
                " WHERE e.subject_id = :id"
            ),
            {"id": niche_id},
        )
        return list(rows.all())


async def test_staff_admin_adds_a_top_level_niche_and_a_child(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str
) -> None:
    admin = await _sign_in(client, app_engine, owner_engine, "admin")
    top = await client.post(
        "/api/admin/niches", json={"slug": f"water-{tag}", "name": " Water & sanitation ", "isic_code": "E36"}
    )
    assert top.status_code == 201, top.text
    parent = top.json()
    assert parent == {
        "id": parent["id"],
        "slug": f"water-{tag}",
        "name": "Water & sanitation",
        "label": "Water & sanitation",
        "parent_slug": None,
        "isic_code": "E36",
        "active": True,
        "sort_order": 0,
    }
    child = await client.post(
        "/api/admin/niches", json={"slug": f"water-kiosks-{tag}", "name": "Water kiosks", "parent_slug": f"water-{tag}"}
    )
    assert child.status_code == 201, child.text
    assert child.json()["label"] == "Water & sanitation › Water kiosks"
    assert child.json()["parent_slug"] == f"water-{tag}"
    assert child.json()["isic_code"] is None
    listed = {n["slug"]: n for n in (await client.get("/api/admin/niches")).json()}
    assert listed[f"water-kiosks-{tag}"] == child.json()

    [top_event] = await _events(owner_engine, parent["id"])
    [child_event] = await _events(owner_engine, child.json()["id"])
    assert tuple(top_event) == (
        "directory.niche_added",
        "staff",
        admin,
        None,
        "niche",
        UUID(parent["id"]),
        {"parent_id": None},
        False,
    )
    assert tuple(child_event) == (
        "directory.niche_added",
        "staff",
        admin,
        None,
        "niche",
        UUID(child.json()["id"]),
        {"parent_id": parent["id"]},  # ids only: no slug, name or ISIC code
        False,
    )


async def test_a_taken_slug_is_409(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str
) -> None:
    await _sign_in(client, app_engine, owner_engine, "admin")
    first = await client.post("/api/admin/niches", json={"slug": f"energy-{tag}", "name": "Energy"})
    assert first.status_code == 201, first.text
    for slug in (f"energy-{tag}", "social-ngo"):  # made here, and seeded
        again = await client.post("/api/admin/niches", json={"slug": slug, "name": "Again"})
        assert again.status_code == 409, again.text
        assert again.json()["detail"]["code"] == "niche_slug_taken"
    async with owner_engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM niches WHERE slug = :s"), {"s": f"energy-{tag}"})).one()
    assert count == (1,)


async def test_a_parent_that_is_not_an_active_top_level_niche_is_422(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str
) -> None:
    retired = f"retired-{tag}"
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en, active) VALUES (:id, :slug, 'Retired', false)"),
            {"id": uuid7(), "slug": retired},
        )
    await _sign_in(client, app_engine, owner_engine, "admin")
    refusals = {
        "networks-telecommunications": "parent_niche_not_top_level",  # a child: the taxonomy has two levels
        retired: "parent_niche_not_top_level",  # top level, but inactive
        f"missing-{tag}": "parent_niche_not_found",
    }
    for parent, code in refusals.items():
        slug = f"child-of-{parent}"[:60] + f"-{tag}"
        response = await client.post("/api/admin/niches", json={"slug": slug, "name": "Child", "parent_slug": parent})
        assert response.status_code == 422, (parent, response.text)
        assert response.json()["detail"]["code"] == code
    async with owner_engine.connect() as conn:
        made = (await conn.execute(text("SELECT count(*) FROM niches WHERE slug LIKE 'child-of-%'"))).scalar_one()
    assert made == 0


@pytest.mark.parametrize(
    "body",
    [
        {"slug": "Bad Slug", "name": "Bad"},
        {"slug": "trailing-", "name": "Bad"},
        {"slug": "x" * 81, "name": "Long"},
        {"slug": "blank-name", "name": "   "},
        {"slug": "long-name", "name": "n" * 121},
        {"slug": "bad-isic", "name": "ISIC", "isic_code": "k64; drop"},
        {"slug": "bad-parent", "name": "Parent", "parent_slug": "Not A Slug"},
        {"slug": "extra-field", "name": "Extra", "active": False},
        {"name": "No slug"},
    ],
)
async def test_a_malformed_body_is_422(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str, body: dict[str, Any]
) -> None:
    await _sign_in(client, app_engine, owner_engine, "admin")
    response = await client.post("/api/admin/niches", json=body)
    assert response.status_code == 422, response.text


async def test_only_staff_admin_may_add_a_niche(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str
) -> None:
    body = {"slug": f"hidden-{tag}", "name": "Hidden"}
    signed_out = await client.post("/api/admin/niches", json=body)
    assert (signed_out.status_code, signed_out.json()) == (404, NOT_FOUND)
    await _sign_in(client, app_engine, owner_engine, None)
    developer = await client.post("/api/admin/niches", json=body)
    assert (developer.status_code, developer.json()) == (404, NOT_FOUND)
    await _sign_in(client, app_engine, owner_engine, "moderator")
    moderator = await client.post("/api/admin/niches", json=body)
    assert moderator.status_code == 403
    assert moderator.json()["detail"]["code"] == "forbidden"
    async with owner_engine.connect() as conn:
        made = (await conn.execute(text("SELECT count(*) FROM niches WHERE slug = :s"), {"s": body["slug"]})).one()
    assert made == (0,)


async def test_a_stale_second_factor_must_step_up_first(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, tag: str
) -> None:
    admin = await _sign_in(client, app_engine, owner_engine, "admin")
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :u"), {"u": admin}
        )
    response = await client.post("/api/admin/niches", json={"slug": f"stale-{tag}", "name": "Stale"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "step_up_required"
