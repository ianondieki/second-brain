"""The public demo's switches, present in every image (REQ-FND-04; docs/platform/tasks/P28.md track PD; D-71).

``PUBLIC_DEMO=true`` (``bridge.config``; refused at start-up unless ``APP_ENV`` is set explicitly to dev or test) makes
the deployment a public demo that anyone may open:

- **The personas.** ``GET /api/public/demo`` (``status``) lists them, and ``POST /api/auth/demo/sign-in`` signs a
  visitor in as one with a single press. Both come from ``bridge.demo.public_access`` (``PERSONA_MODULE``), which the
  backend image deletes unless built with ``WITH_DEV_TOOLS=true`` (``backend/Dockerfile`` removes ``src/bridge/demo``),
  and which is used only while ``PUBLIC_DEMO`` is on and ``APP_ENV`` is dev or test (``persona_module``). A production
  image has no persona code at all, a production process refuses ``PUBLIC_DEMO``, and an image without the module
  answers ``enabled: false`` and 404 for the sign-in.
- **The lock.** ``refuse_in_public_demo`` (``LOCKED``, applied by route) answers 403 ``public_demo_locked`` on every
  other way in, so the persona allowlist is the only one (the password sign-in, its second step and spending a
  magic link), and on every route that would let one visitor lock the others out of a shared persona or put a file on
  the server: sign-up, magic-link and verification requests, password changes, two-step sign-in (enrol, cancel,
  confirm, recovery codes, disable), OAuth (start, callback, unlinking), organisation role changes, every upload that
  keeps a file (proposal and message attachments) and the dev/test clock's move. A step-up and sign-out stay open,
  and so does the certificate file check (``POST /api/verify``: it hashes the body and stores nothing).
  ``tests/unit/test_public_demo_lock.py`` walks the app's routes and fails when a route that takes a file is neither
  locked nor that named exception.
- **Not indexed, not described.** Every API answer carries ``X-Robots-Tag: noindex, nofollow`` (``ROBOTS_HEADERS``,
  ``bridge.main``), and the app serves neither its OpenAPI schema nor the interactive docs.
- **Fictional content.** With ``PUBLIC_DEMO_CONTENT=fictional`` (the default) the seed loads only fictional
  organisations and official-source research excerpts (``bridge.config.fictional_only``; ``bridge.seed.directory`` and
  ``bridge.seed.demo.research``).
"""

from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime
from types import ModuleType
from typing import Final

from fastapi import APIRouter, Depends, Request

from bridge.auth.deps import SettingsDep
from bridge.config import DEMO_ENVS, Settings
from bridge.errors import ApiError
from bridge.public.schemas import DemoPersona, PublicDemo

PERSONA_MODULE: Final = "bridge.demo.public_access"
LOCKED_CODE: Final = "public_demo_locked"
LOCKED_MESSAGE: Final = "This is switched off in the public demo."  # [[COPY-REVIEW]]
ROBOTS_HEADERS: Final = {"X-Robots-Tag": "noindex, nofollow"}
OFF: Final = PublicDemo(enabled=False, personas=[], reset_hour_eat=None)


async def refuse_in_public_demo(settings: SettingsDep) -> None:
    """403 ``public_demo_locked`` while ``PUBLIC_DEMO`` is on; nothing otherwise. A route dependency, so it answers
    before the route reads a body, a session or a file."""
    if settings.public_demo:
        raise ApiError(403, LOCKED_CODE, LOCKED_MESSAGE)


LOCKED: Final = Depends(refuse_in_public_demo)


def frozen_at(request: Request) -> datetime | None:
    """The public demo's freeze instant (``app.state.public_frozen_at``, recorded by ``bridge.main.create_app`` at
    start-up, or ``PUBLIC_DEMO_FROZEN_AT``): the signed-out public reads (``bridge.public``) show only rows created and
    last changed at or before it, so a visitor's text never reaches a page anyone can open signed out. None outside
    the public demo."""
    frozen: datetime | None = getattr(request.app.state, "public_frozen_at", None)
    return frozen


def persona_module(settings: Settings) -> ModuleType | None:
    """``bridge.demo.public_access`` where the public demo runs (``PUBLIC_DEMO`` on, ``APP_ENV`` dev or test) and the
    image carries it; None everywhere else."""
    if not settings.public_demo or settings.app_env not in DEMO_ENVS:
        return None
    try:
        if importlib.util.find_spec(PERSONA_MODULE) is None:
            return None
    except ModuleNotFoundError:  # bridge.demo itself is absent (a production image)
        return None
    return importlib.import_module(PERSONA_MODULE)


def persona_router(settings: Settings) -> APIRouter | None:
    """The persona sign-in router (``POST /api/auth/demo/sign-in``), or None where the public demo does not run."""
    module = persona_module(settings)
    if module is None:
        return None
    router: APIRouter = module.build_router(settings)
    return router


def status(settings: Settings) -> PublicDemo:
    """What ``GET /api/public/demo`` answers: the personas while the public demo runs, else ``OFF``."""
    module = persona_module(settings)
    if module is None:
        return OFF
    personas: list[DemoPersona] = module.personas()
    reset_hour: int = module.RESET_HOUR_EAT
    return PublicDemo(enabled=True, personas=personas, reset_hour_eat=reset_hour)
