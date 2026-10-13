"""REQ-FND-04 (P28 track PD): the public demo's persona allowlist, status route, module fence and robots header,
without a database.

- AT-PD-2: with the mode off, or without the ``bridge.demo`` module (a production image), ``GET /api/public/demo``
  says ``enabled: false`` and the sign-in route is 404; the backend image deletes ``bridge/demo`` unless built with dev
  tools, and staging and production never get the persona module even from settings that skipped validation.
- The allowlist is fixed in code: seven personas in the card's order (Hassan added by the orchestrator), each a demo
  seed account at a reserved ``.example`` domain, with its name and role from the seed's data; the sign-in body takes
  the key only.
- Every API answer says ``X-Robots-Tag: noindex, nofollow`` while the mode is on, and none says it otherwise.
"""

from __future__ import annotations

import importlib.util
import re
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from bridge import public_demo
from bridge.config import BACKEND_DIR, Settings, get_settings
from bridge.demo import public_access
from bridge.errors import ApiError
from bridge.main import create_app
from bridge.seed.demo.data import all_accounts

KEYS = ["amina", "brian", "grace", "peter", "rita", "hassan", "moderator"]
REMOVAL = re.compile(r'^RUN if \[ "\$WITH_DEV_TOOLS" != "true" \]; then rm -rf (\S+(?: \S+)*); fi$', re.MULTILINE)


def public(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


# ----------------------------------------------------------------------------------------------------- allowlist


def test_the_allowlist_is_seven_seeded_demo_accounts_in_order() -> None:
    accounts = {email: (name, what) for email, name, what in all_accounts()}
    assert [p.key for p in public_access.PERSONAS] == KEYS
    assert len({p.email for p in public_access.PERSONAS}) == len(KEYS)
    for persona in public_access.PERSONAS:
        assert persona.email in accounts, persona.email
        assert persona.email.endswith(".example")
    assert public_access.BY_KEY["peter"].email == "signatory@telco-a.example"
    assert public_access.BY_KEY["hassan"].email == "owner@county-c.example"


def test_the_personas_carry_the_seeds_names_roles_and_homes() -> None:
    listed = [(p.key, p.name, p.role, p.detail, p.home) for p in public_access.personas()]
    assert listed == [
        ("amina", "Amina Wanjiru", "developer", "Developer, D2", "/dev"),
        ("brian", "Brian Otieno", "developer", "Developer, D1", "/dev"),
        ("grace", "Grace Mwangi", "org_admin", "Telco A (fixture): owner and admin", "/org"),
        ("peter", "Peter Kamau", "org_signatory", "Telco A (fixture): signatory", "/org"),
        ("rita", "Rita Njeri", "org_reviewer", "Telco A (fixture): reviewer", "/org"),
        ("hassan", "Hassan Abdi", "org_admin", "County Government of C (fixture): owner and admin", "/org"),
        ("moderator", "Staff Moderator (demo)", "staff", "Platform staff: moderator", "/admin"),
    ]


def test_the_sign_in_body_takes_the_key_only() -> None:
    assert public_access.PersonaSignIn(persona="amina").persona == "amina"
    for body in ({"persona": "amina", "email": "admin@staff.example"}, {"email": "amina@developers.example"}, {}):
        with pytest.raises(ValidationError):
            public_access.PersonaSignIn.model_validate(body)


# ---------------------------------------------------------------------------------------------- the module fence


def test_the_status_off_is_empty() -> None:
    assert public_demo.status(get_settings()).model_dump() == {"enabled": False, "personas": [], "reset_hour_eat": None}


def test_the_status_on_lists_the_personas_and_the_reset_hour() -> None:
    status = public_demo.status(public())
    assert (status.enabled, status.reset_hour_eat) == (True, 3)
    assert [p.key for p in status.personas] == KEYS


def test_production_never_has_the_persona_module() -> None:
    """Even with settings that skipped validation (``model_copy``), production and staging get nothing."""
    for app_env in ("staging", "production"):
        assert public_demo.persona_module(public(app_env=app_env)) is None
        assert public_demo.persona_router(public(app_env=app_env)) is None
        assert public_demo.status(public(app_env=app_env)) == public_demo.OFF
        with pytest.raises(RuntimeError):
            public_access.build_router(public(app_env=app_env))
    with pytest.raises(RuntimeError):
        public_access.build_router(get_settings())  # the mode off


@pytest.mark.parametrize("missing", ["bridge.demo.public_access", "bridge.demo"])
def test_an_image_without_the_module_has_no_public_demo(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    real = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object:
        if name == public_demo.PERSONA_MODULE and missing == "bridge.demo":
            raise ModuleNotFoundError("No module named 'bridge.demo'")
        return None if name == missing else real(name, package)

    monkeypatch.setattr("importlib.util.find_spec", find_spec)
    assert public_demo.persona_module(public()) is None
    assert public_demo.persona_router(public()) is None
    assert public_demo.status(public()) == public_demo.OFF


def test_the_backend_image_deletes_the_demo_package_unless_built_with_dev_tools() -> None:
    dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
    removal = REMOVAL.search(dockerfile)
    assert removal is not None
    module = BACKEND_DIR / "src" / "bridge" / "demo" / "public_access.py"
    assert module.is_file()
    assert public_access.__file__ is not None
    assert module.samefile(public_access.__file__)  # the persona code is in the package the image deletes
    assert "src/bridge/demo" in removal.group(1).split()


async def test_the_lock_dependency_refuses_only_in_the_public_demo() -> None:
    await public_demo.refuse_in_public_demo(get_settings())
    with pytest.raises(ApiError) as refused:
        await public_demo.refuse_in_public_demo(public())
    assert refused.value.status_code == 403
    detail: object = refused.value.detail  # an ApiError's detail is a mapping (HTTPException types it as text)
    assert detail == {"code": "public_demo_locked", "message": "This is switched off in the public demo."}


# ---------------------------------------------------------------------------------------- the routes and headers


async def get(settings: Settings, path: str) -> httpx.Response:
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        return await client.get(path)


async def test_get_public_demo_when_off() -> None:
    response = await get(get_settings(), "/api/public/demo")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "personas": [], "reset_hour_eat": None}
    assert response.headers["cache-control"] == "public, max-age=60"
    assert "x-robots-tag" not in response.headers


async def test_get_public_demo_when_on() -> None:
    response = await get(public(), "/api/public/demo")
    assert response.status_code == 200
    body = response.json()
    assert (body["enabled"], body["reset_hour_eat"]) == (True, 3)
    assert body["personas"][3] == {
        "key": "peter",
        "name": "Peter Kamau",
        "role": "org_signatory",
        "detail": "Telco A (fixture): signatory",
        "home": "/org",
    }
    assert [p["key"] for p in body["personas"]] == KEYS
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("path", ["/healthz", "/api/public/demo", "/api/no-such-route", "/api/auth/csrf"])
async def test_every_answer_is_noindex_in_the_public_demo(path: str) -> None:
    response = await get(public(), path)
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "x-robots-tag" not in (await get(get_settings(), path)).headers


async def test_the_sign_in_route_is_404_when_the_mode_is_off() -> None:
    """AT-PD-2: not mounted (a CSRF-valid POST, so the 404 is the router's, not the CSRF guard's 403)."""
    app = create_app(get_settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        token = (await client.get("/api/auth/csrf")).json()["csrf_token"]
        response = await client.post(
            "/api/auth/demo/sign-in", json={"persona": "amina"}, headers={"X-CSRF-Token": token}
        )
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")


async def test_the_sign_in_needs_the_csrf_token() -> None:
    app = create_app(public())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/auth/demo/sign-in", json={"persona": "amina"})
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "csrf_failed")


def test_the_openapi_document_leaves_the_sign_in_out() -> None:
    """Like the test clock, the persona sign-in is a dev-image route: never in the API document."""
    paths = create_app(public()).openapi()["paths"]
    assert "/api/public/demo" in paths
    assert "/api/auth/demo/sign-in" not in paths
