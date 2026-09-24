"""Liveness and readiness (docs/spec/08: Better Stack uptime on /healthz and /readyz)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
async def readyz(request: Request) -> JSONResponse | dict[str, str]:
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception:  # any failure means "not ready"
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}
