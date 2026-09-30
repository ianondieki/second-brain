"""The dev/test clock router (REQ-ENG-12; PLAN.md §8 P5; docs/spec/08 "the test-clock router is excluded from the
production image").

``GET /api/test-clock`` reads the shared clock; ``POST /api/test-clock/advance`` moves it forward through
``app_set_test_clock`` (revision 0003: only forward, at most 366 days, and only where the owner enabled the clock,
which ``python -m bridge.seed`` does for an explicit ``APP_ENV`` of dev, test or staging). Every tracker time, deadline
and evidence time follows ``app_clock_now()``, so moving the clock moves them all, for the API and the worker alike.

Three fences keep it out of production: this module is deleted from the backend image unless the image is built with
``WITH_DEV_TOOLS=true`` (``backend/Dockerfile``; the dev stack sets it), ``bridge.main`` mounts the router only when
``APP_ENV`` is not production and the module exists, and a production database never has the clock enabled. In
staging (real-looking data, several users) only staff admin may use it; in dev and test any signed-in user may.
The routes are left out of the OpenAPI document.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bridge.admin.deps import staff_member
from bridge.auth.deps import Db, current_session
from bridge.config import Settings
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.models.enums import StaffRole

MAX_OFFSET = timedelta(days=366)
_READ = text("SELECT enabled, clock_offset, app_clock_now() AS now FROM test_clock WHERE singleton")
_SET = text("SELECT app_set_test_clock(:offset)")


class ClockOut(BaseModel):
    enabled: bool
    offset_seconds: int
    now: datetime


class AdvanceBody(BaseModel):
    days: int = Field(default=0, ge=0, le=366)
    hours: int = Field(default=0, ge=0, le=24 * 366)


def build_router(settings: Settings) -> APIRouter:
    """The router for ``settings``' environment; never for production."""
    if settings.app_env == "production":
        raise RuntimeError("the test clock is never mounted in production")
    guard = staff_member(StaffRole.ADMIN) if settings.app_env == "staging" else current_session
    router = APIRouter(
        prefix="/api/test-clock",
        tags=["test-clock"],
        include_in_schema=False,
        dependencies=[Depends(guard)],
        responses=ERROR_RESPONSES,
    )

    async def _read(db: Db) -> ClockOut:
        row = (await db.execute(_READ)).one()
        return ClockOut(enabled=row.enabled, offset_seconds=int(row.clock_offset.total_seconds()), now=row.now)

    @router.get("")
    async def read_clock(db: Db) -> ClockOut:
        return await _read(db)

    @router.post("/advance")
    async def advance_clock(body: AdvanceBody, db: Db) -> ClockOut:
        current = await _read(db)
        offset = timedelta(seconds=current.offset_seconds) + timedelta(days=body.days, hours=body.hours)
        if offset > MAX_OFFSET:
            raise ApiError(422, "test_clock_limit", "The test clock moves at most 366 days ahead.")
        try:
            await db.execute(_SET, {"offset": offset})
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "42501":
                raise ApiError(
                    409, "test_clock_disabled", "The test clock is not enabled in this database (run the seed)."
                ) from exc
            raise
        await db.commit()
        return await _read(db)

    return router
