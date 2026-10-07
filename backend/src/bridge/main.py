"""FastAPI application factory (REQ-FND-02). Run: ``uvicorn bridge.main:create_app --factory``."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from bridge import __version__, clock, errors
from bridge.admin.claims import router as claims_admin_router
from bridge.admin.events import router as events_admin_router
from bridge.admin.quiz import router as quiz_admin_router
from bridge.admin.research import router as research_admin_router
from bridge.admin.router import router as admin_router
from bridge.api import health
from bridge.auth import csrf
from bridge.auth.router import me_router as identities_router
from bridge.auth.router import router as auth_router
from bridge.billing.router import plans_router
from bridge.billing.router import router as billing_router
from bridge.config import Settings, get_settings
from bridge.db import API_IDLE_IN_TRANSACTION_MS, create_engine, create_session_factory
from bridge.directory.responsiveness import NoResponsivenessData
from bridge.directory.router import router as directory_router
from bridge.engagements.interest_router import router as interest_router
from bridge.engagements.messages_router import router as messages_router
from bridge.engagements.router import router as engagements_router
from bridge.events.router import router as events_router
from bridge.integrations.sms import sms_provider_from_settings
from bridge.llm.deps import build_runtime as llm_runtime
from bridge.llm.embeddings import embedder_from_settings
from bridge.logging import configure_logging, get_logger
from bridge.matching.matches import router as matches_router
from bridge.matching.router import router as discover_router
from bridge.matching.scouts import router as scouts_router
from bridge.notifications.email import provider_from_settings
from bridge.notifications.in_app_router import router as notifications_router
from bridge.notifications.preferences_router import router as preferences_router
from bridge.problems.briefs_router import router as briefs_router
from bridge.problems.router import router as problems_router
from bridge.profiles.router import public_router as consents_router
from bridge.profiles.router import router as me_router
from bridge.profiles.saved_searches import router as saved_searches_router
from bridge.proposals.assistant_router import router as assistant_router
from bridge.proposals.disclosure_router import router as disclosure_router
from bridge.proposals.originality_router import router as originality_router
from bridge.proposals.pitch_router import router as pitch_router
from bridge.proposals.router import router as proposals_router
from bridge.proposals.shortlist_router import router as shortlist_router
from bridge.provenance.router import router as provenance_router
from bridge.quiz.router import router as quiz_router
from bridge.teams.contributors import router as contributors_router
from bridge.teams.peers import router as peers_router
from bridge.teams.router import blocks_router
from bridge.teams.router import router as teams_router
from bridge.tenancy.router import router as orgs_router

API_PREFIX = "/api"
TEST_CLOCK_MODULE = "bridge.testclock"
log = get_logger(__name__)

# Every /api answer carries the platform clock (REQ-TRACK-03): a page counts a deadline down from it, never from the
# browser's clock alone, so the dev/test clock (make demo-clock, the e2e clock scenarios) moves the countdown too.
APP_NOW_HEADER: Final = "X-App-Now"
APP_NOW_DOC: Final = {
    "description": "The platform clock when the request was answered, in ISO 8601 UTC with a Z (to the millisecond):"
    " on every /api response, errors included. Count deadlines (due_at, deadline_at) down from it, not from the"
    " device's clock; in dev and test it follows the test clock.",
    "schema": {"type": "string", "format": "date-time"},
}
_APP_CLOCK = text("SELECT app_clock_now()")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def dev_clock_router(settings: Settings) -> APIRouter | None:
    """The dev/test clock router (REQ-ENG-12): never in production, and only where the image carries the module
    (``backend/Dockerfile`` deletes it unless built with ``WITH_DEV_TOOLS=true``)."""
    if settings.app_env == "production" or importlib.util.find_spec(TEST_CLOCK_MODULE) is None:
        return None
    router: APIRouter = importlib.import_module(TEST_CLOCK_MODULE).build_router(settings)
    return router


async def app_clock_now(engine: AsyncEngine | None, *, movable: bool) -> datetime:
    """The platform clock for ``X-App-Now``. Where the dev/test clock may move it (every environment but production)
    it is the database's ``app_clock_now()``; a production database never enables that clock, so there it is the wall
    clock without a query. Without a database (an app built without its lifespan, or the database down) it is the wall
    clock, logged as ``app_now.fallback``: the header is for display, and ``overdue`` and ``past_deadline`` stay the
    authority."""
    if movable and engine is not None:
        try:
            async with engine.connect() as conn:  # autocommit: one statement, no BEGIN or ROLLBACK round trips
                autocommit = await conn.execution_options(isolation_level="AUTOCOMMIT")
                now: datetime = (await autocommit.execute(_APP_CLOCK)).scalar_one()
                return now
        except SQLAlchemyError as exc:
            # Never a 500 for the header's sake; a broken or missing dev/test clock shows in the log (the class only).
            log.warning("app_now.fallback", error_type=type(exc).__name__)
    return clock.utcnow()


def stamp(moment: datetime) -> str:
    """``moment`` as ``X-App-Now`` carries it: ISO 8601 in UTC with a Z, to the millisecond."""
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def app_now_headers(request: Request) -> dict[str, str]:
    """``X-App-Now`` as the middleware read it for this request (none outside /api): the 500 handler's, which runs
    outside every middleware."""
    moment: datetime | None = getattr(request.state, "app_now", None)
    return {} if moment is None else {APP_NOW_HEADER: stamp(moment)}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    csrf_key = settings.secret_key.get_secret_value()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.sms_provider = sms_provider_from_settings(settings)  # fails closed (production needs the vendor)
        engine = create_engine(
            settings.database_url.get_secret_value(), idle_in_transaction_timeout_ms=API_IDLE_IN_TRANSACTION_MS
        )
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.email_provider = provider_from_settings(settings)
        # The LLM registry and provider adapters; requests get RoutedLLMClient over the SQL stores (bridge.llm.deps).
        app.state.llm_runtime = llm_runtime(settings)
        try:
            # The teaser embedder runs in the request (publish, the originality check): with EMBEDDER=bge-m3 it loads
            # here, so missing weights stop the API at startup instead of degrading the check (P19-D).
            app.state.embedder = embedder_from_settings(settings, app.state.llm_runtime.registry.embeddings)
            if settings.embedder == "bge-m3":
                await app.state.embedder.embed(["startup check"])
            yield
        finally:
            await app.state.llm_runtime.aclose()
            await engine.dispose()

    app = FastAPI(
        title=f"{settings.product_name} API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if settings.app_env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.responsiveness = NoResponsivenessData()  # the directory score has no data until Phase 3
    errors.install(app, headers=SECURITY_HEADERS, per_request=app_now_headers)  # one error shape (bridge.errors)
    movable_clock = settings.app_env != "production"  # the dev/test clock never runs in production

    def csrf_passes(request: Request) -> bool:
        """The CSRF check (an HMAC, no I/O): safe methods pass; a state-changing request echoes its token."""
        return csrf.request_passes(
            csrf_key,
            method=request.method,
            cookie=request.cookies.get(settings.csrf_cookie_name),
            header=request.headers.get(csrf.HEADER),
            binding=csrf.binding_for(request.cookies.get(settings.session_cookie_name)),
        )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Every state-changing /api request must echo the CSRF cookie in X-CSRF-Token (docs/spec/08 Auth)."""
        if request.url.path.startswith(API_PREFIX) and not csrf_passes(request):
            return JSONResponse(
                status_code=403,
                content={"detail": {"code": "csrf_failed", "message": "Refresh the page and try again."}},
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.middleware("http")
    async def app_now(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """``X-App-Now`` on every /api answer the CSRF guard lets through, errors included (the 500 handler reads the
        same instant from ``request.state``: ``app_now_headers``). Outside production reading it takes a pooled
        connection, so a request the guard will refuse is checked first (the same HMAC, no I/O) and gets neither the
        query nor the header; the guard still answers its 403. A safe-method request, signed in or not, does cost one
        clock query outside production (THREAT_MODEL.md D, residual); production never queries for it."""
        if not request.url.path.startswith(API_PREFIX) or not csrf_passes(request):
            return await call_next(request)
        now = await app_clock_now(getattr(request.app.state, "engine", None), movable=movable_clock)
        request.state.app_now = now
        response = await call_next(request)
        response.headers[APP_NOW_HEADER] = stamp(now)
        return response

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(orgs_router)
    app.include_router(me_router)
    app.include_router(identities_router)
    app.include_router(consents_router)
    app.include_router(directory_router)
    app.include_router(admin_router)
    app.include_router(research_admin_router)
    app.include_router(claims_admin_router)
    app.include_router(quiz_admin_router)
    app.include_router(events_admin_router)
    app.include_router(provenance_router)
    app.include_router(pitch_router)
    app.include_router(proposals_router)
    app.include_router(assistant_router)
    app.include_router(originality_router)
    app.include_router(disclosure_router)
    app.include_router(shortlist_router)
    app.include_router(problems_router)
    app.include_router(briefs_router)
    app.include_router(engagements_router)
    app.include_router(messages_router)
    app.include_router(plans_router)
    app.include_router(billing_router)
    app.include_router(interest_router)
    app.include_router(scouts_router)
    app.include_router(matches_router)
    app.include_router(discover_router)
    app.include_router(saved_searches_router)
    app.include_router(notifications_router)
    app.include_router(preferences_router)
    app.include_router(quiz_router)
    app.include_router(events_router)
    app.include_router(peers_router)
    app.include_router(teams_router)
    app.include_router(blocks_router)
    app.include_router(contributors_router)
    clock_router = dev_clock_router(settings)
    if clock_router is not None:
        app.include_router(clock_router)
    # X-Forwarded-For is trusted only from TRUSTED_PROXIES (throttling keys on the client IP). Added last = outermost.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=[h.strip() for h in settings.trusted_proxies.split(",")])

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["headers"] = {APP_NOW_HEADER: APP_NOW_DOC}
        schema["components"]["securitySchemes"] = {
            "session": {"type": "apiKey", "in": "cookie", "name": settings.session_cookie_name},
            "csrf": {"type": "apiKey", "in": "header", "name": csrf.HEADER},
        }
        schema["security"] = [{"session": [], "csrf": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app
