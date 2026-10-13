"""REQ-FND-04 (P28 track PD, AT-PD-4): the public demo's lock, walked over the app's own routes.

The rule: every route that takes a file (a multipart form, ``UploadFile``, ``File``/``Form`` parameters, or a raw body
declared as binary in its OpenAPI request body) keeps it, and so carries ``refuse_in_public_demo``, unless it is one
of the named exceptions in ``STORES_NOTHING`` (today only the certificate file check, ``POST /api/verify``, which
hashes the body and stores nothing; the orchestrator's decision). A future upload route cannot ship unlocked, and a
module that reads a raw request body must expose that route as a declared upload, or the walk would miss it. The
locked routes are exactly the register below (the password sign-in, its second step and link sign-in, since the
persona allowlist is the only way in; then the card's list: credentials, sign-in methods, role changes, uploads that
keep a file, the clock), and each answers 403 ``public_demo_locked`` while the mode is on, before any session, body
or database.
A new state-changing account or membership route (sign-in methods, an address, a password, a second factor, members,
an export or a deletion) fails the walk until it is locked or reviewed as open.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, params
from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext, iter_route_contexts

import bridge
from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.main import create_app
from bridge.public_demo import refuse_in_public_demo

# The locked routes (method, path): the password sign-in and its second step (the persona allowlist is the only way
# in), then the card's list. Add a route here when you lock it.
LOCKED_ROUTES = frozenset(
    {
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/mfa/verify"),
        ("POST", "/api/auth/signup"),
        ("POST", "/api/auth/magic-link"),
        ("POST", "/api/auth/magic-link/consume"),
        ("POST", "/api/auth/verify-email/resend"),
        ("POST", "/api/auth/password"),
        ("POST", "/api/auth/totp/enrol"),
        ("DELETE", "/api/auth/totp/enrol"),
        ("POST", "/api/auth/totp/confirm"),
        ("POST", "/api/auth/totp/recovery-codes"),
        ("POST", "/api/auth/totp/disable"),
        ("POST", "/api/auth/oauth/{provider}/start"),
        ("GET", "/api/auth/oauth/{provider}/callback"),
        ("DELETE", "/api/auth/identities/{identity_id}"),
        ("PUT", "/api/orgs/{org_id}/members/{user_id}/roles"),
        ("POST", "/api/me/proposals/{proposal_id}/attachments"),
        ("POST", "/api/engagements/{engagement_id}/messages/attachments"),
        ("POST", "/api/test-clock/advance"),
        ("POST", "/api/me/calendar-feed"),  # a feed URL anyone may open would publish a visitor's text
        ("POST", "/api/orgs/{org_id}/calendar-feed"),
    }
)
# Routes that take a file but keep nothing, so they stay open in the public demo, each with its reason. Add one only
# when the route provably stores no part of the body (no object store, no row, no log of its content).
STORES_NOTHING = {
    ("POST", "/api/verify"): "the certificate file check hashes the body in memory and stores nothing",
}
UPLOADS = frozenset(
    {
        ("POST", "/api/me/proposals/{proposal_id}/attachments"),
        ("POST", "/api/engagements/{engagement_id}/messages/attachments"),
        ("POST", "/api/verify"),
    }
)
RAW_BODY = re.compile(r"\brequest\.(?:stream|form|body)\(|\bUploadFile\b|\bFile\(|\bForm\(")
FILE_TYPES = ("multipart/", "application/octet-stream")


def public_settings(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


def contexts(app: FastAPI) -> Iterator[RouteContext]:
    for route in iter_route_contexts(app.routes):
        if getattr(route, "dependant", None) is not None:
            yield route


def calls(dependant: Dependant) -> Iterator[Any]:
    for sub in dependant.dependencies:
        yield sub.call
        yield from calls(sub)


def is_locked(route: RouteContext) -> bool:
    return refuse_in_public_demo in set(calls(route.dependant))


def takes_a_file(route: RouteContext) -> bool:
    """A multipart or form parameter anywhere in its dependencies, or a request body declared as a file."""

    def form_fields(dependant: Dependant) -> Iterator[bool]:
        for param in dependant.body_params:
            yield isinstance(param.field_info, params.File | params.Form)
        for sub in dependant.dependencies:
            yield from form_fields(sub)

    if any(form_fields(route.dependant)):
        return True
    body = (route.openapi_extra or {}).get("requestBody", {})
    for content_type, media in body.get("content", {}).items():
        schema = media.get("schema", {})
        if content_type.startswith(FILE_TYPES) or schema.get("format") == "binary":
            return True
    return False


def key(route: RouteContext) -> list[tuple[str, str]]:
    return [(method, str(route.path)) for method in sorted(route.methods or ())]


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """The public demo's app: every router mounted (the persona sign-in and the dev/test clock included)."""
    return create_app(public_settings())


def test_every_route_that_takes_a_file_is_locked_unless_it_stores_nothing(app: FastAPI) -> None:
    uploads = {k for route in contexts(app) if takes_a_file(route) for k in key(route)}
    assert uploads == UPLOADS  # the walk finds the known uploads (and would find a new one)
    unlocked = {k for route in contexts(app) if takes_a_file(route) and not is_locked(route) for k in key(route)}
    stray = sorted(unlocked - set(STORES_NOTHING))
    assert not stray, f"upload routes without bridge.public_demo.LOCKED: {stray}"
    assert unlocked == set(STORES_NOTHING)  # each named exception is a real, open upload route


def test_every_module_that_reads_a_raw_body_declares_its_upload(app: FastAPI) -> None:
    """A route that reads the request body itself is found only through its declared request body: every module that
    does so must be one whose upload the walk found (a new raw-body route must declare it, and then it is checked)."""
    package = Path(bridge.__file__).parent
    readers = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if RAW_BODY.search(path.read_text(encoding="utf-8"))
    }
    declared = {
        Path(inspect.getfile(route.endpoint)).relative_to(package).as_posix()
        for route in contexts(app)
        if takes_a_file(route) and route.endpoint is not None
    }
    assert readers, "the scan found nothing: the pattern no longer matches the upload code"
    assert readers <= declared, f"raw-body readers without a declared upload route: {sorted(readers - declared)}"


def test_the_locked_routes_are_exactly_the_register(app: FastAPI) -> None:
    locked = {k for route in contexts(app) if is_locked(route) for k in key(route)}
    assert locked == LOCKED_ROUTES


def test_the_persona_sign_in_and_reads_stay_open(app: FastAPI) -> None:
    """What a visitor needs is never locked: the persona sign-in (the only way in), a step-up, sign-out."""
    open_routes = {k for route in contexts(app) if not is_locked(route) for k in key(route)}
    for needed in (
        ("POST", "/api/auth/demo/sign-in"),
        ("POST", "/api/auth/step-up"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/auth/me"),
        ("GET", "/api/test-clock"),
        ("GET", "/api/public/demo"),
    ):
        assert needed in open_routes, needed


# The account routes that stay open in the public demo, each reviewed: the persona sign-in (the only way in), a
# step-up (a persona session's second factor already counts; a code would still be checked) and sign-out.
OPEN_ACCOUNT_ROUTES = frozenset(
    {
        ("POST", "/api/auth/demo/sign-in"),
        ("POST", "/api/auth/step-up"),
        ("POST", "/api/auth/logout"),
    }
)
ACCOUNT_PATHS = re.compile(r"^/api/auth/|^/api/me/identities|/members(/|$)|/email|/password|/totp|/export|/delete")
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def test_every_account_and_membership_change_is_classified(app: FastAPI) -> None:
    """A new state-changing route under ``/api/auth`` or ``/api/me/identities``, or one about members, an address, a
    password, a second factor, an export or a deletion, fails here until it is locked or reviewed as open (an email
    change or a DSR route must not reach the public demo unlocked by accident)."""
    found = {
        k
        for route in contexts(app)
        for k in key(route)
        if k[0] in WRITES and ACCOUNT_PATHS.search(k[1]) and k not in UPLOADS
    }
    unclassified = sorted(found - LOCKED_ROUTES - OPEN_ACCOUNT_ROUTES)
    assert not unclassified, f"lock these (bridge.public_demo.LOCKED) or review them as open: {unclassified}"
    assert found >= OPEN_ACCOUNT_ROUTES


CLOCK_MOVE = ("POST", "/api/test-clock/advance")  # behind the clock router's sign-in guard: 401 first when signed out


def concrete(path: str) -> str:
    return re.sub(r"\{([a-z_]+)\}", lambda m: "github" if m.group(1) == "provider" else str(UUID(int=1)), path)


async def answer(app: FastAPI, method: str, path: str) -> httpx.Response:
    """``method path`` as a signed-out visitor with a valid CSRF token. The database is never reached: the session
    factory points at an address nothing listens on, and a signed-out request opens no connection."""
    app.state.session_factory = create_session_factory(create_engine("postgresql+psycopg://probe@localhost:1/probe"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        token = (await client.get("/api/auth/csrf")).json()["csrf_token"]
        return await client.request(method, concrete(path), json={}, headers={"X-CSRF-Token": token})


LOCKED_JSON = {"detail": {"code": "public_demo_locked", "message": "This is switched off in the public demo."}}


@pytest.mark.parametrize(("method", "path"), sorted(LOCKED_ROUTES - {CLOCK_MOVE}))
async def test_each_locked_route_answers_403_while_the_mode_is_on(app: FastAPI, method: str, path: str) -> None:
    """Before any session, body or database: a signed-out visitor gets the lock's 403 (the card's AT-PD-4)."""
    response = await answer(app, method, path)
    assert response.status_code == 403, response.text
    assert response.json() == LOCKED_JSON
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


async def test_the_clock_asks_for_a_session_first(app: FastAPI) -> None:
    """The clock router's guard runs before the route's lock: signed out it is 401 (signed in, 403: the integration
    test)."""
    response = await answer(app, *CLOCK_MOVE)
    assert (response.status_code, response.json()["detail"]["code"]) == (401, "unauthenticated")


async def test_the_lock_is_off_outside_the_public_demo() -> None:
    """Mode off: the same request reaches the route (here: 401 for a password change without a session)."""
    response = await answer(create_app(get_settings()), "POST", "/api/auth/password")
    assert (response.status_code, response.json()["detail"]["code"]) == (401, "unauthenticated")
    assert "x-robots-tag" not in response.headers
