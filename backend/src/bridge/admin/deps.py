"""Staff access to the admin console (REQ-ADM-01; Phase 1 follow-up 5; docs/spec/03 platform staff roles).

``staff_member(*roles)`` admits a signed-in user whose ``users.staff_role`` is set and whose TOTP is enrolled, with a
second factor verified within ``STEP_UP_MAX_AGE_HOURS`` (ADR-002: 12 h). Everyone else (signed out, second factor
still pending, not staff, or staff without TOTP) gets the same **404** as an unknown resource, so the console is not
discoverable. Enrolled staff lacking the route's role get 403, and those whose second factor is older than the
step-up window get 403 ``step_up_required``. The database applies the same rule to staff tables through
``app_is_staff()`` (revision 0002: staff role, active, TOTP enrolled).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from bridge.auth.deps import SettingsDep, ensure_step_up, optional_session
from bridge.auth.sessions import LiveSession
from bridge.errors import forbidden, not_found
from bridge.models.enums import StaffRole


@dataclass(frozen=True, slots=True)
class StaffContext:
    role: StaffRole
    live: LiveSession


def staff_member(*required: StaffRole) -> Callable[..., Awaitable[StaffContext]]:
    async def dependency(
        live: Annotated[LiveSession | None, Depends(optional_session)], settings: SettingsDep
    ) -> StaffContext:
        if live is None or live.row.mfa_pending:
            raise not_found()
        user = live.user
        if user.staff_role is None or user.totp_enabled_at is None:
            raise not_found()
        role = StaffRole(user.staff_role)
        if required and role not in required:
            raise forbidden()
        ensure_step_up(live, settings)
        return StaffContext(role, live)

    return dependency


StaffMember = Annotated[StaffContext, Depends(staff_member())]
StaffAdmin = Annotated[StaffContext, Depends(staff_member(StaffRole.ADMIN))]
StaffModerator = Annotated[StaffContext, Depends(staff_member(StaffRole.ADMIN, StaffRole.MODERATOR))]
