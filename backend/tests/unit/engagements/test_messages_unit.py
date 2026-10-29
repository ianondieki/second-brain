"""REQ-ENG-11: the thread's pure parts. What a message body may hold, how an upload's name is read, how a download
link is signed and bound to its reader, how the database's refusals become API errors, and the jobs' registration."""

from __future__ import annotations

from typing import Any, get_args
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from bridge.config import get_settings
from bridge.engagements import message_files, message_notify, messages
from bridge.engagements import state_machine as sm
from bridge.engagements.message_schemas import MessageBody, ReadBody, ReportBody, ReportReason, ThreadStatus
from bridge.engagements.models import MESSAGE_REPORT_REASONS
from bridge.engagements.service import Party
from bridge.jobs import message_uploads, notifications
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.models.enums import EngagementActorRole, EngagementParty, OrgRole
from bridge.notifications.email import FakeEmailProvider
from bridge.storage.objects import InMemoryObjectStore

ENGAGEMENT = UUID("01900000-0000-7000-8000-00000000000a")
MESSAGE = UUID("01900000-0000-7000-8000-00000000000b")
FILE = UUID("01900000-0000-7000-8000-00000000000c")
USER = UUID("01900000-0000-7000-8000-00000000000d")
OTHER = UUID("01900000-0000-7000-8000-00000000000e")


class _Live:
    def __init__(self, user_id: UUID) -> None:
        self.user = type("U", (), {"id": user_id})()


def party(user_id: UUID = USER, *, developer: bool = True, roles: frozenset[Any] = frozenset()) -> Party:
    actor = sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER) if developer else sm.Actor(EngagementParty.ORG, roles)
    return Party(ENGAGEMENT, _Live(user_id), actor, OTHER, frozenset({OrgRole.VIEWER}))  # type: ignore[arg-type]


def test_a_body_is_plain_text_of_one_to_four_thousand_characters() -> None:
    assert MessageBody(body="Line one\r\nLine two\tend").body == "Line one\nLine two\tend"
    assert MessageBody(body="x" * 4000).attachment_ids == []
    for bad in ("", "   \n ", "x" * 4001, "a\x00b", "a\rb", "a\x7fb"):
        with pytest.raises(ValidationError):
            MessageBody(body=bad)
    with pytest.raises(ValidationError):
        MessageBody(body="Hi", attachment_ids=[FILE, FILE])
    with pytest.raises(ValidationError):
        MessageBody(body="Hi", attachment_ids=[UUID(int=n) for n in range(6)])
    with pytest.raises(ValidationError):
        MessageBody.model_validate({"body": "Hi", "sender_party": "org"})


def test_report_reasons_are_codes_from_the_fixed_list() -> None:
    assert get_args(ReportReason) == MESSAGE_REPORT_REASONS  # the database's list (app_report_message)
    assert ReportBody(reasons=["spam", "abuse", "spam"]).reasons == ["spam", "abuse"]
    for bad in ([], ["rude"], ["spam"] * 6):
        with pytest.raises(ValidationError):
            ReportBody.model_validate({"reasons": bad})
    assert ReadBody().up_to is None


def test_an_uploads_name_is_its_last_segment_without_control_characters() -> None:
    assert message_files.file_name_of("..%2F..%2Fetc%2Fpasswd") == "passwd"
    assert message_files.file_name_of("C:%5Cdocs%5Cplan.pdf") == "plan.pdf"
    assert message_files.file_name_of("a%0Ab%E2%80%8Fc.pdf") == "abc.pdf"
    assert message_files.file_name_of(None) == "attachment"
    assert message_files.file_name_of("%20%20") == "attachment"
    assert len(message_files.file_name_of("n" * 300)) == 255
    with pytest.raises(UnicodeDecodeError):
        message_files.file_name_of("%FF%FE")


def test_an_object_key_holds_ids_only() -> None:
    assert message_files.object_key(ENGAGEMENT, FILE) == f"messages/{ENGAGEMENT}/{FILE}"


def test_a_link_is_signed_for_one_reader_one_file_and_one_expiry() -> None:
    settings = get_settings()
    signed = message_files.sign_link(settings, party(), MESSAGE, FILE, 1_800_000_000)
    assert len(signed) == 64
    assert signed == message_files.sign_link(settings, party(), MESSAGE, FILE, 1_800_000_000)
    assert signed != message_files.sign_link(settings, party(OTHER), MESSAGE, FILE, 1_800_000_000)
    assert signed != message_files.sign_link(settings, party(), MESSAGE, OTHER, 1_800_000_000)
    assert signed != message_files.sign_link(settings, party(), MESSAGE, FILE, 1_800_000_001)


class _Diag:
    def __init__(self, message: str, constraint: str | None) -> None:
        self.message_primary = message
        self.constraint_name = constraint


class _Orig(Exception):
    def __init__(self, sqlstate: str, message: str = "", constraint: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.diag = _Diag(message, constraint)


def refused(sqlstate: str, message: str = "", constraint: str | None = None, **kwargs: Any) -> tuple[int, str] | None:
    error = messages.refusal(DBAPIError("stmt", {}, _Orig(sqlstate, message, constraint)), party(**kwargs))
    if error is None:
        return None
    assert isinstance(error.detail, dict)
    return error.status_code, str(error.detail["code"])


def test_the_databases_refusals_become_api_errors() -> None:
    opens = "engagement_messages: the thread opens at INTEREST_CONFIRMED"
    assert refused("55000", opens) == (409, "thread_not_open")
    assert refused("55000", opens, developer=False) == (403, "thread_not_open")
    assert refused("55000", "engagement_messages: the engagement ended in CLOSED; its thread is read-only") == (
        409,
        "thread_read_only",
    )
    assert refused("42501", "no engagement of the caller's with that id") == (404, "not_found")
    assert refused("42501", "new row violates row-level security policy", developer=False) == (403, "cannot_post")
    assert refused("54000") == (429, "too_many_reports")
    joins = "engagement_message_attachments: an upload joins a message within 24 hours of its upload"
    assert refused("23514", joins) == (422, "attachment_expired")
    assert refused("22023", "app_report_message: the reasons are one or more of spam, abuse") == (422, "invalid")
    assert refused("23514", "", "engagement_message_attachments_at_most_5") == (422, "too_many_attachments")
    assert refused("23514", "", "ck_engagement_message_attachments_attached_only_when_clean") == (
        409,
        "attachment_pending",
    )
    for sqlstate in ("23514", "23505", "40001", "40P01"):
        assert refused(sqlstate) == (409, "conflict")
    assert refused("22001") is None


def test_only_the_developer_or_an_acting_member_posts_on_an_open_thread() -> None:
    open_, closed = ThreadStatus.OPEN, ThreadStatus.READ_ONLY
    assert messages.can_post(party(), open_)
    assert not messages.can_post(party(), closed)
    assert not messages.can_post(party(developer=False), open_)  # a viewer
    assert messages.can_post(party(developer=False, roles=frozenset({EngagementActorRole.REVIEWER})), open_)


def test_the_jobs_are_registered() -> None:
    assert "bridge.jobs.message_uploads" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    assert app.tasks[message_notify.TASK].queue == "notifications"
    task = app.tasks[message_uploads.TASK]
    assert (task.queue, task.lock) == ("engagements", "engagements:purge_message_uploads")
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[message_uploads.TASK] == "17 * * * *"


async def test_the_n18_task_delivers_and_retries_while_an_email_is_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    outcome = {"done": True}

    async def deliver(factory: object, provider: object, settings: object, **kwargs: Any) -> bool:
        calls.append(kwargs)
        return outcome["done"]

    monkeypatch.setattr(message_notify, "deliver", deliver)
    notifications.use_runtime(
        notifications.NotificationRuntime(get_settings(), session_factory=object(), email_provider=FakeEmailProvider())  # type: ignore[arg-type]
    )
    ids = {"engagement_id": str(ENGAGEMENT), "message_id": str(MESSAGE), "developer_id": str(USER)}
    try:
        await notifications.engagement_message_notify(**ids)
        assert calls == [{"engagement_id": ENGAGEMENT, "message_id": MESSAGE, "developer_id": USER}]
        outcome["done"] = False
        with pytest.raises(notifications.EmailStillQueued):
            await notifications.engagement_message_notify(**ids)
    finally:
        notifications.use_runtime(None)


async def test_the_purge_task_runs_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, object]] = []

    async def purge(factory: object, store: object) -> int:
        calls.append((factory, store))
        return 0

    factory, store = object(), InMemoryObjectStore()
    monkeypatch.setattr(message_uploads, "purge_stale_uploads", purge)
    message_uploads.use_runtime(message_uploads.PurgeRuntime(session_factory=factory, object_store=store))  # type: ignore[arg-type]
    try:
        await message_uploads.purge_message_uploads(timestamp=0)
    finally:
        message_uploads.use_runtime(None)
    assert calls == [(factory, store)]
    runtime = message_uploads.PurgeRuntime(get_settings())
    assert runtime.settings is get_settings()
    assert runtime.object_store is runtime.object_store
    assert runtime.session_factory is runtime.session_factory
    assert message_uploads.runtime() is message_uploads.runtime()
    message_uploads.use_runtime(None)
    assert message_uploads.PurgeRuntime().settings is get_settings()


class _Rows:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[str]]:
        return self._rows


class _Session:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.rows, self.committed = rows, False

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, statement: object) -> _Rows:
        return _Rows(self.rows)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.committed = False


async def test_the_purge_deletes_only_keys_under_the_threads_prefix() -> None:
    store = InMemoryObjectStore()
    for object_key in ("messages/e/a", "proposals/p/a"):
        await store.put("uploads", object_key, b"x", content_type="application/pdf")
    session = _Session([("messages/e/a",), ("proposals/p/a",)])
    assert await message_files.purge_stale_uploads(lambda: session, store) == 2  # type: ignore[arg-type]
    assert session.committed
    assert set(store.objects) == {("uploads", "proposals/p/a")}


def test_the_thread_and_the_history_name_an_unreadable_sender_alike() -> None:
    from bridge.engagements.history import FORMER_MEMBER, sender_name

    assert sender_name({USER: "Amina Otieno"}, USER) == "Amina Otieno"
    assert sender_name({}, OTHER) == FORMER_MEMBER == "Former member"
