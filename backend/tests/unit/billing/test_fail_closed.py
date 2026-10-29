"""REQ-BIL-01, REQ-BIL-08 and the REQ-BIL-04 interface: the billing rules that refuse rather than guess.

- A checkout is for exactly one payer (a developer or an organisation), and its lock is that payer's.
- A plan limit that is not a whole number (a catalogue mistake) raises instead of being read as one.
- ``for_subject`` takes exactly one subject and refuses before reading anything.
- Signup refuses to start without the side's default plan in the database (it never skips billing).
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.billing import entitlements
from bridge.billing.checkout import Subject
from bridge.billing.entitlements import Entitlements
from bridge.billing.service import PlansNotSeededError, start_free_subscription
from bridge.config import get_settings
from bridge.models.enums import PlanSide


class _Untouched:
    """A session that fails the test if anything uses it."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the session was used ({name})")


class _NoPlanRow:
    """A session whose plans table has no row for the code asked for (nothing seeded)."""

    def __init__(self) -> None:
        self.added: list[object] = []

    async def execute(self, *_args: object, **_kwargs: object) -> Any:
        class Result:
            def scalar_one_or_none(self) -> None:
                return None

        return Result()

    def add(self, row: object) -> None:
        self.added.append(row)


def test_a_checkout_is_for_exactly_one_payer_and_locks_on_it() -> None:
    user, org = uuid4(), uuid4()
    with pytest.raises(ValueError, match="exactly one"):
        Subject()
    with pytest.raises(ValueError, match="exactly one"):
        Subject(user_id=user, org_id=org)
    developer, organisation = Subject(user_id=user), Subject(org_id=org)
    assert (developer.side, developer.key) == (PlanSide.DEVELOPER, f"checkout:{user}")
    assert (organisation.side, organisation.key) == (PlanSide.ORG, f"checkout:{org}")


@pytest.mark.parametrize("value", [True, "5", 2.5, [3]], ids=["bool", "text", "fraction", "list"])
def test_a_limit_that_is_not_a_whole_number_raises(value: object) -> None:
    """``True`` would otherwise count as 1 and ``"5"`` as nothing: a malformed catalogue fails loudly."""
    ent = Entitlements("dev_free", PlanSide.DEVELOPER, {"active_proposals": value})
    with pytest.raises(TypeError, match="active_proposals is not a numeric limit"):
        ent.limit("active_proposals")


async def test_entitlements_are_for_exactly_one_subject_and_refused_before_any_query() -> None:
    db = cast(AsyncSession, _Untouched())
    with pytest.raises(ValueError, match="exactly one"):
        await entitlements.for_subject(db, get_settings())
    with pytest.raises(ValueError, match="exactly one"):
        await entitlements.for_subject(db, get_settings(), user_id=uuid4(), org_id=uuid4())


@pytest.mark.parametrize("side", [PlanSide.DEVELOPER, PlanSide.ORG])
async def test_signup_refuses_without_the_default_plan_in_the_database(side: PlanSide) -> None:
    session = _NoPlanRow()
    subject = {"user_id": uuid4()} if side is PlanSide.DEVELOPER else {"org_id": uuid4()}
    with pytest.raises(PlansNotSeededError) as refused:
        await start_free_subscription(cast(AsyncSession, session), get_settings(), side=side, **subject)
    assert str(refused.value) == ("dev_free" if side is PlanSide.DEVELOPER else "org_claimed")
    assert session.added == []  # no subscription without its plan
