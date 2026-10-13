"""The public demo's personas and one-press sign-in (REQ-FND-04; docs/platform/tasks/P28.md track PD; D-71).

``POST /api/auth/demo/sign-in {"persona": "<key>"}`` signs the visitor in as one of the fixed demo accounts in
``PERSONAS`` and answers ``SessionResponse`` with the session cookie, as ``POST /api/auth/login`` does.
``bridge.public_demo.status`` lists the same personas for ``GET /api/public/demo``. Dev and test only.

Security reasoning (for the security review):

- **Impossible in production, three fences.** This module lives in ``bridge/demo``, which ``backend/Dockerfile``
  deletes unless the image is built with ``WITH_DEV_TOOLS=true``; ``bridge.main`` mounts the router only where the
  module exists and ``PUBLIC_DEMO`` is on (``bridge.public_demo.persona_router``); and ``Settings`` refuses to start
  with ``PUBLIC_DEMO=true`` unless ``APP_ENV`` is set explicitly to dev or test. ``build_router`` and the session
  helper (``bridge.auth.service.start_demo_persona_session``) check the mode again.
- **Never an arbitrary account.** The request names a key, never an address: the addresses are the fixed allowlist
  below, and the body allows no other field (``extra="forbid"``: an ``email`` is refused with 422). The account must
  also be ``ACTIVE`` and flagged ``users.demo_account``, which only the owner role (the demo seed) can set; anything
  else, like an unknown key, is 400 ``unknown_persona`` with the same words, so the answer tells nothing about an
  account.
- **The only way in.** The password sign-in, its second step and spending a magic link are locked in the public demo,
  so the published demo password cannot open an account outside the allowlist (the demo staff admin, say).
- **No second factor to waive for a real person.** The session's second factor counts as done (``mfa_pending``
  false, ``mfa_verified_at`` now) because the persona's TOTP secret is a public demo value anyway; the helper refuses
  any account that is not an active demo account. A persona's step-ups (an endorsement, a signature) are therefore
  recorded with the method ``totp`` in the demo's fictional data, though no code was typed.
- **Visitors cannot take a persona away from each other.** Every route that changes a credential, a sign-in method or
  an organisation role, every upload that keeps a file and the clock answer 403 ``public_demo_locked``
  (``bridge.public_demo.LOCKED``), and the nightly reset wipes everything else a visitor did.
- **CSRF and throttling as every auth POST.** The CSRF middleware of ``bridge.main`` covers this route like every
  state-changing ``/api`` request (the visitor first reads ``GET /api/auth/csrf``). Each attempt, refused ones
  included, is counted on the ``login_attempts`` ledger (HMAC digests only, ``bridge.auth.throttle``), then 429
  ``too_many_attempts``: ``SIGN_INS_PER_MINUTE`` a minute per client address when the address is global and not a
  trusted proxy's; otherwise (behind Codespaces' forwarder, a bare ``docker run -p``, or a client that sends its own
  X-Forwarded-For to an untrusted hop, every visitor may share or fake one address) one bucket for all such attempts
  with ``SHARED_SIGN_INS_PER_MINUTE``, which raises the cost of locking the others out (one client still can, at
  about five requests a second; per-visitor throttling needs an edge that sets X-Forwarded-For and is listed in
  ``TRUSTED_PROXIES``), and one warning a minute in the log.
- **Sessions stay bounded.** Signing in with a session cookie ends that session first (switching persona), and a
  persona keeps at most ``MAX_SESSIONS_PER_PERSONA`` live sessions: the oldest beyond are revoked.
- **Nothing secret in the logs.** The session token goes only into the cookie; the audit event (``auth.login``,
  ``{"method": "demo_persona", "persona": <key>}``) and a refusal's log line name the persona key only.
"""

from __future__ import annotations

import ipaddress
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth import service, sessions, throttle
from bridge.auth.cookies import set_session
from bridge.auth.deps import Db, SettingsDep, client_ip
from bridge.auth.router import MESSAGES, user_out
from bridge.auth.schemas import SessionResponse
from bridge.config import DEMO_ENVS, Settings
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.logging import get_logger
from bridge.models.enums import OrgRole, UserStatus
from bridge.public.schemas import DemoPersona, PersonaRole
from bridge.seed.demo.data import DEVELOPERS, ORGS, PEER_DEVELOPERS, STAFF

RESET_HOUR_EAT: Final = 3  # the image's supervisor wipes and seeds the demo again at 03:00 East Africa Time
SIGN_INS_PER_MINUTE: Final = 30  # per global client address, refused attempts included
SHARED_SIGN_INS_PER_MINUTE: Final = 300  # every address that tells no visitor apart, together
THROTTLE_PURPOSE: Final = "demo_persona"
SHARED_PURPOSE: Final = "demo_persona_shared"
SHARED_WARNING_EVERY: Final = 60.0  # seconds between two "per-visitor throttling is unavailable" lines
MAX_SESSIONS_PER_PERSONA: Final = 500  # live sessions a persona keeps; the oldest beyond are revoked
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Persona:
    key: str
    email: str
    role: PersonaRole
    home: str  # the web path the visitor lands on


# The allowlist: the only accounts the sign-in ever opens, in the order the persona picker shows them. Every address is
# a demo seed account (bridge.seed.demo.data) at a reserved .example domain.
PERSONAS: Final[tuple[Persona, ...]] = (
    Persona("amina", "amina@developers.example", "developer", "/dev"),
    Persona("brian", "brian@developers.example", "developer", "/dev"),
    Persona("grace", "owner@telco-a.example", "org_admin", "/org"),
    Persona("peter", "signatory@telco-a.example", "org_signatory", "/org"),
    Persona("rita", "reviewer@telco-a.example", "org_reviewer", "/org"),
    Persona("halima", "owner@state-d.example", "org_admin", "/org"),
    Persona("moderator", "moderator@staff.example", "staff", "/admin"),
)
BY_KEY: Final = {persona.key: persona for persona in PERSONAS}


def _roles(roles: tuple[OrgRole, ...]) -> str:
    names = [role.value for role in roles]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def seeded_people() -> dict[str, tuple[str, str]]:
    """Every demo seed account as address -> (display name, one line of what it is). [[COPY-REVIEW]]"""
    people = {dev.email: (dev.display_name, f"Developer, {dev.level.value.upper()}") for dev in DEVELOPERS}
    people |= {dev.email: (dev.display_name, f"Developer, {dev.level.value.upper()}") for dev in PEER_DEVELOPERS}
    for org in ORGS:
        for seat in ([org.owner] if org.owner else []) + list(org.seats):
            people[seat.email] = (seat.display_name, f"{org.legal_name}: {_roles(seat.roles)}")
    people |= {staff.email: (staff.display_name, f"Platform staff: {staff.role.value}") for staff in STAFF}
    return people


@lru_cache(maxsize=1)
def personas() -> list[DemoPersona]:
    """The personas as ``GET /api/public/demo`` lists them: names and details from the demo seed's data."""
    people = seeded_people()
    return [
        DemoPersona(key=p.key, name=people[p.email][0], role=p.role, detail=people[p.email][1], home=p.home)
        for p in PERSONAS
    ]


class PersonaSignIn(BaseModel):
    """The persona's key only: an address, a password or any other field is refused (422)."""

    model_config = ConfigDict(extra="forbid")

    persona: str = Field(min_length=1, max_length=40, description='A key from GET /api/public/demo, e.g. "amina"')


def unknown_persona() -> ApiError:
    return ApiError(400, "unknown_persona", MESSAGES["unknown_persona"])


def per_visitor(ip: str, settings: Settings) -> bool:
    """Whether ``ip`` tells visitors apart: a global address that is not one of ``TRUSTED_PROXIES``. A loopback,
    private, link-local or otherwise non-global address, a trusted proxy's own address and an unreadable one say
    nothing about who is asking (Codespaces' port forwarder, a bare ``docker run -p``, a proxy that adds no
    X-Forwarded-For: then every visitor shares one address)."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if not address.is_global:
        return False
    for entry in (part.strip() for part in settings.trusted_proxies.split(",")):
        if entry == "*":
            return False
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return False
        except ValueError:
            continue
    return True


@dataclass(slots=True)
class _Warning:
    last: float | None = None


_SHARED_WARNING: Final = _Warning()


def warn_shared_bucket(now: float) -> bool:
    """Log, at most once every ``SHARED_WARNING_EVERY`` seconds of ``now`` (monotonic), that the sign-in has no
    per-visitor address to throttle on; True when it logged."""
    if _SHARED_WARNING.last is not None and now - _SHARED_WARNING.last < SHARED_WARNING_EVERY:
        return False
    _SHARED_WARNING.last = now
    # Per call, so a logger cached under an earlier configuration is never reused (as ``deliveries.send_email``).
    get_logger(__name__).warning("auth.demo_persona_shared_bucket")  # per-visitor throttling is unavailable
    return True


async def allow_attempt(db: AsyncSession, settings: Settings, ip: str) -> bool:
    """Count one sign-in attempt (the caller commits) and say whether it is within the minute's limit: per address
    (``SIGN_INS_PER_MINUTE``) when the address tells visitors apart, else in one bucket for all of them
    (``SHARED_SIGN_INS_PER_MINUTE``, so one client cannot lock everyone out with a few requests)."""
    secret = settings.secret_key.get_secret_value()
    if per_visitor(ip, settings):
        keys, limit = throttle.ip_keys(secret, THROTTLE_PURPOSE, ip), SIGN_INS_PER_MINUTE
    else:
        warn_shared_bucket(time.monotonic())
        keys, limit = throttle.ip_keys(secret, SHARED_PURPOSE, "shared"), SHARED_SIGN_INS_PER_MINUTE
    if await throttle.ip_blocked(db, keys, limit=limit):
        log.info("auth.demo_persona_throttled")
        return False
    throttle.record(db, keys, succeeded=True)
    return True


def build_router(settings: Settings) -> APIRouter:
    """The sign-in router; only for the public demo (``PUBLIC_DEMO`` on, ``APP_ENV`` dev or test)."""
    if not settings.public_demo or settings.app_env not in DEMO_ENVS:
        raise RuntimeError("the persona sign-in is mounted only in the public demo (PUBLIC_DEMO, APP_ENV dev or test)")
    router = APIRouter(prefix="/api/auth/demo", tags=["auth"], include_in_schema=False, responses=ERROR_RESPONSES)

    @router.post("/sign-in")
    async def sign_in(
        body: PersonaSignIn, request: Request, response: Response, db: Db, settings: SettingsDep
    ) -> SessionResponse:
        """Sign in as a persona: 200 with the session cookie; 400 ``unknown_persona`` for a key outside the
        allowlist or an account that is not an active demo account; 429 ``too_many_attempts`` past the limit."""
        if not await allow_attempt(db, settings, client_ip(request)):
            raise ApiError(429, "too_many_attempts", MESSAGES["too_many_attempts"])
        persona = BY_KEY.get(body.persona)
        user = None if persona is None else await service.user_by_email(db, persona.email)
        if persona is None or user is None or user.status != UserStatus.ACTIVE or not user.demo_account:
            await db.commit()  # keep the throttle entry
            log.info("auth.demo_persona_refused", persona=persona.key if persona else None)
            raise unknown_persona()
        presented = request.cookies.get(settings.session_cookie_name)
        current = None if not presented else await sessions.lookup(db, presented)
        if current is not None:
            await sessions.revoke(db, current.row)  # switching persona ends the session the browser had
        live = await service.start_demo_persona_session(db, settings, user, request.headers.get("user-agent"))
        await sessions.revoke_beyond(db, user.id, keep=MAX_SESSIONS_PER_PERSONA)
        await audit(
            db,
            "auth.login",
            actor_user_id=user.id,
            subject_type="user",
            subject_id=user.id,
            payload={"method": "demo_persona", "persona": persona.key},
        )
        await db.commit()
        set_session(response, settings, live.token)
        return SessionResponse(user=user_out(user), mfa_required=False)

    return router
