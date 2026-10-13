"""REQ-FND-04 (P28 track PD): ``service.start_demo_persona_session`` counts the second factor as done only for an active
demo account while the public demo runs in dev or test. Whoever calls it, it refuses everything else before it touches
the database (the session here has no bind, so any statement would fail loudly)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth import service
from bridge.auth.models import User
from bridge.config import Settings, get_settings
from bridge.models.enums import UserStatus


def public(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


def account(*, demo: bool = True, status: UserStatus = UserStatus.ACTIVE) -> User:
    return User(id=uuid4(), email="amina@developers.example", display_name="Amina", status=status, demo_account=demo)


@pytest.mark.parametrize(
    ("settings", "user", "reason"),
    [
        pytest.param(get_settings(), account(), "only in the public demo", id="mode-off"),
        pytest.param(public(app_env="staging"), account(), "only in the public demo", id="staging"),
        pytest.param(public(app_env="production"), account(), "only in the public demo", id="production"),
        pytest.param(public(), account(demo=False), "only an active demo account", id="not-a-demo-account"),
        pytest.param(
            public(), account(status=UserStatus.SUSPENDED), "only an active demo account", id="suspended-account"
        ),
    ],
)
async def test_the_persona_session_is_refused_outside_its_one_case(settings: Settings, user: User, reason: str) -> None:
    db = AsyncSession()
    try:
        with pytest.raises(RuntimeError, match=reason):
            await service.start_demo_persona_session(db, settings, user, "pytest")
        assert not db.new  # nothing was added
    finally:
        await db.close()
