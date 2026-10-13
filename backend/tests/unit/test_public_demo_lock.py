"""REQ-FND-04 (P28 track PD, AT-PD-4): the public demo's lock, walked over the app's own routes.

The rule: every route that takes a file (a multipart form, ``UploadFile``, ``File``/``Form`` parameters, or a raw body
declared as binary in its OpenAPI request body) keeps it, and so carries ``refuse_in_public_demo``, unless it is one
of the named exceptions in ``STORES_NOTHING`` (today only the certificate file check, ``POST /api/verify``, which
hashes the body and stores nothing; the orchestrator's decision). Whether a route takes a file is decided per route,
from its parameters, its declared request body and its endpoint's own code (``reads_raw_body`` follows the calls it
makes into ``bridge``), so a future upload route cannot ship unlocked even when it declares nothing. The
locked routes are exactly the register below (the password sign-in, its second step and link sign-in, since the
persona allowlist is the only way in; then the card's list: credentials, sign-in methods, role changes, uploads that
keep a file, the clock), and each answers 403 ``public_demo_locked`` while the mode is on, before any session, body
or database.
A new state-changing account or membership route (sign-in methods, an address, a password, a second factor, members,
an export, a deletion, invitations or claims) fails the walk until it is locked or reviewed as open.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Request, params
from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext, iter_route_contexts

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
        # Staff are read-only (the moderator persona): every staff write.
        ("POST", "/api/admin/niches"),
        ("POST", "/api/admin/moderation/cases/{case_id}/decision"),
        ("POST", "/api/admin/research/runs"),
        ("POST", "/api/admin/research/candidates/{problem_id}/decision"),
        ("POST", "/api/admin/research/trends/{card_id}/decision"),
        ("POST", "/api/admin/research/trend-runs"),
        ("POST", "/api/admin/quiz/sets/{set_id}/decision"),
        ("POST", "/api/admin/quiz/questions/{question_id}/pull"),
        ("POST", "/api/admin/quiz/questions/{question_id}/restore"),
        ("POST", "/api/admin/events"),
        ("POST", "/api/admin/events/{event_id}/decision"),
        ("POST", "/api/admin/events/{event_id}/cancel"),
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
RAW_READS = frozenset({"stream", "body", "form"})  # a Request's methods that read the body
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


def form_fields(dependant: Dependant) -> Iterator[bool]:
    for param in dependant.body_params:
        yield isinstance(param.field_info, params.File | params.Form)
    for sub in dependant.dependencies:
        yield from form_fields(sub)


def declares_a_file(route: RouteContext) -> bool:
    """A request body declared as a file in its OpenAPI request body (a multipart form, an octet stream, binary)."""
    body = (route.openapi_extra or {}).get("requestBody", {})
    for content_type, media in body.get("content", {}).items():
        schema = media.get("schema", {})
        if content_type.startswith(FILE_TYPES) or schema.get("format") == "binary":
            return True
    return False


def _resolve(node: ast.expr, scope: dict[str, Any]) -> Any:
    """What a call's target names in ``scope``: a module-level name, or a function of an imported module."""
    if isinstance(node, ast.Name):
        return scope.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        owner = scope.get(node.value.id)
        return getattr(owner, node.attr, None) if inspect.ismodule(owner) else None
    return None


def reads_raw_body(func: Callable[..., Any], depth: int = 4, seen: set[Any] | None = None) -> bool:
    """Whether ``func``, or a function of ours it calls (``depth`` calls deep), reads the request body itself:
    ``.stream()``, ``.body()`` or ``.form()`` on a parameter annotated ``Request``. Read from the code, per route, so a
    route that reads its body without declaring it is still found."""
    func = inspect.unwrap(func)
    seen = set() if seen is None else seen
    if func in seen or depth < 0:
        return False
    seen.add(func)
    try:
        tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    except (OSError, TypeError):
        return False
    requests = {name for name, p in inspect.signature(func).parameters.items() if "Request" in str(p.annotation)}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if (
            isinstance(target, ast.Attribute)
            and target.attr in RAW_READS
            and isinstance(target.value, ast.Name)
            and target.value.id in requests
        ):
            return True
        called = _resolve(target, func.__globals__)
        ours = inspect.isfunction(called) and called.__module__.split(".")[0] in {
            "bridge",
            func.__module__.split(".")[0],
        }
        if ours and reads_raw_body(called, depth - 1, seen):
            return True
    return False


def takes_a_file(route: RouteContext) -> bool:
    """A multipart or form parameter anywhere in its dependencies, a request body declared as a file, or an endpoint
    that reads the raw body itself (``reads_raw_body``), each decided for this route alone."""
    endpoint = route.endpoint
    return (
        any(form_fields(route.dependant))
        or declares_a_file(route)
        or (endpoint is not None and reads_raw_body(endpoint))
    )


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


def test_every_route_that_reads_a_raw_body_declares_it(app: FastAPI) -> None:
    """Per route: an endpoint that reads its body itself also declares it as a file in its OpenAPI request body (so
    API clients and the walk above agree), and the call-graph reading finds every declared upload."""
    readers = {k for route in contexts(app) if route.endpoint and reads_raw_body(route.endpoint) for k in key(route)}
    declared = {k for route in contexts(app) if declares_a_file(route) for k in key(route)}
    assert readers == declared == UPLOADS


async def _read_helper(request: Request) -> bytes:
    return b"".join([chunk async for chunk in request.stream()])


def test_the_reader_follows_helpers_and_ignores_json_routes() -> None:
    """The scratch mutation of the review: a new route reading its body through a helper, declared nowhere, is found;
    a JSON route is not."""

    async def scratch(proposal_id: UUID, request: Request) -> dict[str, int]:
        return {"size": len(await _read_helper(request))}

    async def json_only(proposal_id: UUID, request: Request) -> dict[str, str]:
        return {"path": request.url.path}

    assert reads_raw_body(scratch)
    assert not reads_raw_body(json_only)
    probe = FastAPI()
    probe.post("/api/me/proposals/{proposal_id}/scratch")(scratch)
    [route] = [r for r in contexts(probe) if str(r.path).endswith("/scratch")]
    assert takes_a_file(route)
    assert not is_locked(route)  # so the rule above would name it


def test_every_staff_write_is_locked_and_every_staff_read_open(app: FastAPI) -> None:
    """The moderator persona reads the queues and decides nothing: a new staff write fails here until it is locked."""
    staff = [(k, is_locked(route)) for route in contexts(app) for k in key(route) if k[1].startswith("/api/admin")]
    assert [k for k, locked in staff if k[0] in WRITES and not locked] == []
    assert [k for k, locked in staff if k[0] not in WRITES and locked] == []
    assert sum(1 for k, _ in staff if k[0] == "GET") >= 10  # the walk sees the staff reads


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
# A developer's team-up invitations (REQ-DEV-03) stay open, reviewed: an invitation is a note from one demo developer
# to another about a problem, never a credential, a sign-in method or an organisation's membership; it locks nobody
# out of a persona, and the nightly reset wipes it.
OPEN_TEAM_INVITATIONS = frozenset(
    {
        ("POST", "/api/me/teams/invitations"),
        ("POST", "/api/me/teams/invitations/{invitation_id}/accept"),
        ("POST", "/api/me/teams/invitations/{invitation_id}/decline"),
        ("POST", "/api/me/teams/invitations/{invitation_id}/withdraw"),
    }
)
ACCOUNT_PATHS = re.compile(
    r"^/api/auth/|^/api/me/identities|/members(/|$)|/email|/password|/totp|/export|/delete|invitations|claims"
)
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def test_every_account_and_membership_change_is_classified(app: FastAPI) -> None:
    """A new state-changing route under ``/api/auth`` or ``/api/me/identities``, or one about members, an address, a
    password, a second factor, an export, a deletion, invitations or claims, fails here until it is locked or
    reviewed as open (an email change, a DSR route, a member invitation or a claim decision must not reach the public
    demo unlocked by accident)."""
    found = {
        k
        for route in contexts(app)
        for k in key(route)
        if k[0] in WRITES and ACCOUNT_PATHS.search(k[1]) and k not in UPLOADS
    }
    unclassified = sorted(found - LOCKED_ROUTES - OPEN_ACCOUNT_ROUTES - OPEN_TEAM_INVITATIONS)
    assert not unclassified, f"lock these (bridge.public_demo.LOCKED) or review them as open: {unclassified}"
    assert found >= OPEN_ACCOUNT_ROUTES | OPEN_TEAM_INVITATIONS


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
