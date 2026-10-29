"""The staff dependency (REQ-ADM-01; Phase 1 follow-up 5): staff role + enrolled TOTP + a second factor verified within
the step-up window. Everyone else gets the same 404 as an unknown resource, so the console is not discoverable;
enrolled staff lacking the route's role get 403 and staff with a stale second factor 403 ``step_up_required``."""

from __future__ import annotations

from collections.abc import AsyncIterator
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


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as c:
        yield c


async def _user(owner_engine: AsyncEngine, *, staff_role: str | None = None, totp: bool = True) -> UUID:
    async with owner_engine.begin() as conn:
        if totp or staff_role is None:
            return await w.add_user(conn, f"staff-{uuid4().hex[:10]}@example.test", "Staff", staff_role=staff_role)
        user_id = uuid7()
        await conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, staff_role)"
                " VALUES (:id, :email, 'Staff without TOTP', CAST(:role AS staff_role))"
            ),
            {"id": user_id, "email": f"staff-{uuid4().hex[:10]}@example.test", "role": staff_role},
        )
        return user_id


async def _set_session(owner_engine: AsyncEngine, user_id: UUID, assignment: str) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"UPDATE sessions SET {assignment} WHERE user_id = :u"), {"u": user_id})


async def _assert_hidden(client: httpx.AsyncClient) -> None:
    for path in ("/api/admin/me", "/api/admin/niches"):
        response = await client.get(path)
        assert response.status_code == 404, path
        assert response.json() == NOT_FOUND


async def test_signed_out_callers_get_404(client: httpx.AsyncClient) -> None:
    await _assert_hidden(client)


@pytest.mark.parametrize("mfa_verified", [False, True])
async def test_non_staff_get_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine, mfa_verified: bool
) -> None:
    await sign_in_as(client, app_engine, await _user(owner_engine), mfa_verified=mfa_verified)
    await _assert_hidden(client)


async def test_staff_without_totp_get_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    user_id = await _user(owner_engine, staff_role="admin", totp=False)
    await sign_in_as(client, app_engine, user_id, mfa_verified=False)
    await _assert_hidden(client)


async def test_staff_with_the_second_factor_pending_get_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    user_id = await _user(owner_engine, staff_role="admin")
    await sign_in_as(client, app_engine, user_id, mfa_verified=False)
    await _set_session(owner_engine, user_id, "mfa_pending = true")
    await _assert_hidden(client)


async def test_suspended_staff_get_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    user_id = await _user(owner_engine, staff_role="admin")
    await sign_in_as(client, app_engine, user_id, mfa_verified=True)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET status = 'suspended' WHERE id = :u"), {"u": user_id})
    await _assert_hidden(client)


async def test_staff_admin_with_totp_gets_200(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    await sign_in_as(client, app_engine, await _user(owner_engine, staff_role="admin"), mfa_verified=True)
    me = await client.get("/api/admin/me")
    assert me.status_code == 200
    assert me.json() == {"role": "admin"}
    niches = await client.get("/api/admin/niches")
    assert niches.status_code == 200
    by_slug = {n["slug"]: n for n in niches.json()}
    assert by_slug["networks-telecommunications"]["label"] == "ICT › Networks & Telecommunications"
    assert by_slug["networks-telecommunications"]["parent_slug"] == "ict"
    assert by_slug["social-ngo"]["parent_slug"] is None


async def test_inactive_niches_show_to_staff_but_not_in_the_picker(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    slug = f"retired-{uuid4().hex[:8]}"
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en, active) VALUES (:id, :slug, 'Retired', false)"),
            {"id": uuid7(), "slug": slug},
        )
    try:
        await sign_in_as(client, app_engine, await _user(owner_engine, staff_role="admin"), mfa_verified=True)
        staff_view = {n["slug"]: n for n in (await client.get("/api/admin/niches")).json()}
        assert staff_view[slug]["active"] is False
        picker = (await client.get("/api/directory/niches")).json()
        assert slug not in {n["slug"] for n in picker}
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM niches WHERE slug = :slug"), {"slug": slug})


async def test_staff_with_a_stale_second_factor_must_step_up(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    user_id = await _user(owner_engine, staff_role="admin")
    await sign_in_as(client, app_engine, user_id, mfa_verified=True)
    await _set_session(owner_engine, user_id, "mfa_verified_at = now() - interval '13 hours'")
    response = await client.get("/api/admin/me")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "step_up_required"


async def test_a_moderator_reaches_the_console_but_not_admin_routes(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    await sign_in_as(client, app_engine, await _user(owner_engine, staff_role="moderator"), mfa_verified=True)
    assert (await client.get("/api/admin/me")).json() == {"role": "moderator"}
    response = await client.get("/api/admin/niches")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"
