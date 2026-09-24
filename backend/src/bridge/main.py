"""FastAPI application factory (REQ-FND-02). Run: ``uvicorn bridge.main:create_app --factory``."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from bridge import __version__
from bridge.api import health
from bridge.auth import csrf
from bridge.auth.router import router as auth_router
from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.logging import configure_logging
from bridge.notifications.email import provider_from_settings
from bridge.profiles.router import router as me_router
from bridge.tenancy.router import router as orgs_router

API_PREFIX = "/api"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    csrf_key = settings.secret_key.get_secret_value()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url.get_secret_value())
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.email_provider = provider_from_settings(settings)
        try:
            yield
        finally:
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
    return app
