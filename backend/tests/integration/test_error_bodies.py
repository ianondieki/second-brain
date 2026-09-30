"""REQ-SEC-04, REQ-FND-01 (P16-E1 items 1 and 6) on the real routes: a refused sign-in never echoes the password, the
address or the link token it was sent (FastAPI's 422 quotes each invalid value), and an unknown path answers like
a hidden resource."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.api import make_client

PASSWORD = "correct-horse-battery-staple-" * 9  # 261 characters: over the 256 the login accepts
ADDRESS = "wanjiku.kamau@example"  # no dot in the domain: not an address the API accepts
TOKEN = "short-link-token"  # a magic-link token is 20 to 200 characters


async def test_a_refused_sign_in_never_echoes_what_was_typed(app_engine: AsyncEngine) -> None:
    async with make_client(app_engine) as client:
        login = await client.post("/api/auth/login", json={"email": ADDRESS, "password": PASSWORD})
        consume = await client.post("/api/auth/magic-link/consume", json={"token": TOKEN})
        signup = await client.post(
            "/api/auth/signup",
            json={"email": ADDRESS, "password": PASSWORD, "display_name": "Wanjiku Kamau", "accept_terms": "yes"},
        )
    for response in (login, consume, signup):
        assert response.status_code == 422, response.text
        assert all(set(error) == {"loc", "msg", "type"} for error in response.json()["detail"])
        assert not [echo for echo in (PASSWORD[:40], "wanjiku", TOKEN) if echo in response.text.lower()]
    assert {tuple(error["loc"]) for error in login.json()["detail"]} == {("body", "email"), ("body", "password")}


async def test_an_unknown_path_answers_like_a_hidden_resource(app_engine: AsyncEngine) -> None:
    async with make_client(app_engine) as client:
        unknown = await client.get("/api/orgs/not-a-route/at-all")
        hidden = await client.get("/api/admin/me")  # signed out: the console answers 404 not_found
    assert unknown.status_code == hidden.status_code == 404
    assert unknown.json() == hidden.json() == {"detail": {"code": "not_found", "message": "Not found."}}
