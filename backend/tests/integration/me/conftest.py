"""The palette's and the calendar's scene, built once per module (``tests.integration.me.scene``), and a signed-in
client per person."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.api import make_client, sign_in_as
from tests.integration.me.scene import Scene, build

SignedIn = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


@pytest.fixture(scope="module")
async def scene(owner_engine: AsyncEngine) -> Scene:
    return await build(owner_engine)


@pytest.fixture
def signed_in(app_engine: AsyncEngine) -> SignedIn:
    """``signed_in(user_id, mfa_verified=True)``: a client signed in as that person (second factor given unless
    told otherwise)."""

    @asynccontextmanager
    async def open_client(user_id: UUID, *, mfa_verified: bool = True) -> AsyncIterator[httpx.AsyncClient]:
        async with make_client(app_engine) as client:
            await sign_in_as(client, app_engine, user_id, mfa_verified=mfa_verified)
            yield client

    return open_client
