"""FastAPI application factory (REQ-FND-02). Run: ``uvicorn bridge.main:create_app --factory``."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from bridge import __version__, errors
from bridge.admin.claims import router as claims_admin_router
from bridge.admin.research import router as research_admin_router
from bridge.admin.router import router as admin_router
from bridge.api import health
from bridge.auth import csrf
from bridge.auth.router import me_router as identities_router
from bridge.auth.router import router as auth_router
from bridge.billing.router import plans_router
from bridge.billing.router import router as billing_router
from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.directory.responsiveness import NoResponsivenessData
from bridge.directory.router import router as directory_router
from bridge.engagements.interest_router import router as interest_router
from bridge.engagements.router import router as engagements_router
from bridge.integrations.sms import sms_provider_from_settings
from bridge.llm.deps import build_runtime as llm_runtime
from bridge.llm.embeddings import embedder_from_settings
from bridge.logging import configure_logging
from bridge.matching.matches import router as matches_router
from bridge.matching.router import router as discover_router
from bridge.matching.scouts import router as scouts_router
from bridge.notifications.email import provider_from_settings
from bridge.problems.briefs_router import router as briefs_router
from bridge.problems.router import router as problems_router
from bridge.profiles.router import public_router as consents_router
from bridge.profiles.router import router as me_router
from bridge.proposals.assistant_router import router as assistant_router
from bridge.proposals.disclosure_router import router as disclosure_router
from bridge.proposals.originality_router import router as originality_router
from bridge.proposals.pitch_router import router as pitch_router
from bridge.proposals.router import router as proposals_router
from bridge.provenance.router import router as provenance_router
from bridge.tenancy.router import router as orgs_router

API_PREFIX = "/api"
TEST_CLOCK_MODULE = "bridge.testclock"

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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    csrf_key = settings.secret_key.get_secret_value()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.sms_provider = sms_provider_from_settings(settings)  # fails closed (production needs the vendor)
        engine = create_engine(settings.database_url.get_secret_value())
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
    errors.install(app, headers=SECURITY_HEADERS)  # one error shape (bridge.errors)

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Every state-changing /api request must echo the CSRF cookie in X-CSRF-Token (docs/spec/08 Auth)."""
        if request.url.path.startswith(API_PREFIX) and not csrf.request_passes(
            csrf_key,
            method=request.method,
            cookie=request.cookies.get(settings.csrf_cookie_name),
            header=request.headers.get(csrf.HEADER),
            binding=csrf.binding_for(request.cookies.get(settings.session_cookie_name)),
        ):
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
    app.include_router(provenance_router)
    app.include_router(pitch_router)
    app.include_router(proposals_router)
    app.include_router(assistant_router)
    app.include_router(originality_router)
    app.include_router(disclosure_router)
    app.include_router(problems_router)
    app.include_router(briefs_router)
    app.include_router(engagements_router)
    app.include_router(plans_router)
    app.include_router(billing_router)
    app.include_router(interest_router)
    app.include_router(scouts_router)
    app.include_router(matches_router)
    app.include_router(discover_router)
    clock_router = dev_clock_router(settings)
    if clock_router is not None:
        app.include_router(clock_router)
    # X-Forwarded-For is trusted only from TRUSTED_PROXIES (throttling keys on the client IP). Added last = outermost.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=[h.strip() for h in settings.trusted_proxies.split(",")])

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "session": {"type": "apiKey", "in": "cookie", "name": settings.session_cookie_name},
            "csrf": {"type": "apiKey", "in": "header", "name": csrf.HEADER},
        }
        schema["security"] = [{"session": [], "csrf": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
    return app
