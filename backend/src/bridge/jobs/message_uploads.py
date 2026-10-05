"""The thread's staged-upload purge (REQ-ENG-11; ``bridge.engagements.message_files.purge_stale_uploads``).

``engagements.purge_message_uploads`` runs every hour (minute 17, UTC): the staged uploads revision 0008's
``app_purge_stale_message_uploads`` finds can never be sent (infected, or left unsent, or on an engagement that ended)
are deleted, then their files from the object store. One run at a time (lock ``engagements:purge_message_uploads``); no
retry: the next run picks up whatever this one could not do. The runtime (session factory, object store) is built
from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements.message_files import purge_stale_uploads
from bridge.jobs.app import app
from bridge.storage.objects import ObjectStore, object_store_from_settings

TASK: Final = "engagements.purge_message_uploads"
QUEUE: Final = "engagements"
LOCK: Final = "engagements:purge_message_uploads"
CRON: Final = "17 * * * *"


class PurgeRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        object_store: ObjectStore | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._object_store = object_store

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = create_session_factory(create_engine(self.settings.database_url.get_secret_value()))
        return self._session_factory

    @property
    def object_store(self) -> ObjectStore:
        if self._object_store is None:
            self._object_store = object_store_from_settings(self.settings)
        return self._object_store


_runtime: PurgeRuntime | None = None


def runtime() -> PurgeRuntime:
    global _runtime
    if _runtime is None:
        _runtime = PurgeRuntime()
    return _runtime


def use_runtime(value: PurgeRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="engagements-purge-message-uploads-hourly")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def purge_message_uploads(timestamp: int) -> None:
    del timestamp  # the shared clock decides (app_clock_now() in the database)
    rt = runtime()
    await purge_stale_uploads(rt.session_factory, rt.object_store)
