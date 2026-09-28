"""REQ-PROV-04 (D1 phone verification) through the API; AC-IP-5 (``test_d1_required``).

A developer asks for a code for a Kenyan mobile number, receives it through the fake ``SmsProvider`` and confirms it;
``app_confirm_phone_otp`` compares the keyed digest in SQL and raises the profile from D0 to D1. Five wrong codes lock a
code, codes expire after 10 minutes, sends are throttled per user, number and IP, another user cannot confirm a code,
and neither the number nor the SMS text reaches a log line or an audit event.

D2 (KYC ``ManualReview``, AC-IP-9 ``test_kyc_purge``) needs the object store of T2.4 and follows in T2.10b.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import datetime, timedelta
from itertools import count
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

import bridge.clock
from bridge.auth.crypto import keyed_digest
from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.integrations.sms import FakeSmsProvider, SmsError
from bridge.profiles import verification
from bridge.profiles.models import DeveloperProfile
from bridge.profiles.verification import D1Developer
from tests.integration.api import make_client, sign_in_as, sms_outbox

_ips = count(1)
_numbers = count(100_000)

PROBE = "/api/test-only/proposals/{proposal_id}/register"


def new_ip() -> str:
    n = next(_ips)
    return f"10.77.{n // 250}.{n % 250 + 1}"


def new_number() -> tuple[str, str]:
    """A fresh Kenyan mobile number: (as typed, E.164)."""
    tail = f"{next(_numbers):06d}"
    return f"0712 {tail[:3]} {tail[3:]}", f"+254712{tail}"


async def add_user(owner_engine: AsyncEngine, *, developer: bool = True, level: str = "d0") -> UUID:
    user_id = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :email, 'Dev', now())"),
            {"id": user_id, "email": f"d1-{uuid4().hex[:10]}@example.com"},
        )
        if developer:
            await conn.execute(
                text(
                    "INSERT INTO developer_profiles (user_id, handle, verification_level)"
                    " VALUES (:id, :handle, CAST(:level AS dev_verification))"
                ),
                {"id": user_id, "handle": f"d1-{user_id.hex[-12:]}", "level": level},
            )
    return user_id


Client = Callable[..., Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def signed_in(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> AsyncIterator[Client]:
    """``await signed_in()`` gives a client signed in as a new D0 developer, from its own client IP."""
    async with AsyncExitStack() as stack:

        async def make(user_id: UUID | None = None, *, developer: bool = True) -> httpx.AsyncClient:
            uid = user_id or await add_user(owner_engine, developer=developer)
            client = await stack.enter_async_context(make_client(app_engine))
            client.headers["X-Forwarded-For"] = new_ip()  # its own throttle bucket (the harness proxy is trusted)
            await sign_in_as(client, app_engine, uid, mfa_verified=False)
            client.user_id = uid  # type: ignore[attr-defined]
            return client

        yield make


def user_of(client: httpx.AsyncClient) -> UUID:
    user_id: UUID = client.user_id  # type: ignore[attr-defined]
    return user_id


def last_code(client: httpx.AsyncClient) -> str:
    match = re.search(r"\b(\d{6})\b", sms_outbox(client).outbox[-1].text)
    assert match
    return match.group(1)


async def ask(client: httpx.AsyncClient, phone: str) -> httpx.Response:
    return await client.post("/api/me/verification/phone", json={"phone": phone})


async def confirm(client: httpx.AsyncClient, verification_id: str, code: str) -> httpx.Response:
    return await client.post(f"/api/me/verification/phone/{verification_id}/confirm", json={"code": code})


async def level_of(client: httpx.AsyncClient) -> str:
    level: str = (await client.get("/api/me/profile")).json()["verification_level"]
    return level


async def code_row(owner_engine: AsyncEngine, verification_id: str) -> dict[str, Any]:
    async with owner_engine.connect() as conn:
        row = await conn.execute(
            text("SELECT user_id, phone_e164, otp_hash, attempts, verified_at FROM phone_verifications WHERE id = :id"),
            {"id": verification_id},
        )
        return dict(row.mappings().one())


def at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: moment)


def mount_registration_probe(client: httpx.AsyncClient) -> None:
    """A stand-in for the publish route of T2.3 (not built yet): a registration handler guarded by ``require_d1``
    exactly as the real one will be (``profile: D1Developer``)."""

    async def register(proposal_id: UUID, profile: D1Developer) -> dict[str, str]:
        assert isinstance(profile, DeveloperProfile)
        return {"status": "registered", "proposal_id": str(proposal_id)}

    client.app.add_api_route(PROBE, register, methods=["POST"])  # type: ignore[attr-defined]


# ----------------------------------------------------------------------------------------------------- AC-IP-5


async def test_d1_required(signed_in: Client, app_engine: AsyncEngine) -> None:
    """AC-IP-5: a developer without D1 who attempts a registration gets 403; after D1 the same call goes through."""
    developer = await signed_in()
    mount_registration_probe(developer)
    url = PROBE.format(proposal_id=uuid7())

    refused = await developer.post(url)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "d1_required"

    typed, _ = new_number()
    sent = (await ask(developer, typed)).json()
    assert (await confirm(developer, sent["verification_id"], last_code(developer))).status_code == 200
    allowed = await developer.post(url)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "registered"

    no_profile = await signed_in(developer=False)  # an organisation-only account has no developer level at all
    mount_registration_probe(no_profile)
    assert (await no_profile.post(url)).json()["detail"]["code"] == "d1_required"

    async with make_client(app_engine) as anonymous:
        mount_registration_probe(anonymous)
        assert (await anonymous.post(url)).status_code == 401


# ------------------------------------------------------------------------------------------------------ the flow


async def test_the_right_code_raises_the_profile_to_d1(signed_in: Client, owner_engine: AsyncEngine) -> None:
    developer = await signed_in()
    typed, e164 = new_number()
    before = bridge.clock.utcnow()
    response = await ask(developer, typed)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["phone_masked"] == e164[:4] + "******" + e164[-3:]
    assert body["attempts_allowed"] == 5
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=10) <= expires - before <= timedelta(minutes=10, seconds=30)

    [sms] = sms_outbox(developer).outbox
    assert sms.to == e164
    code = last_code(developer)
    assert "10 minutes" in sms.text

    row = await code_row(owner_engine, body["verification_id"])
    assert row["user_id"] == user_of(developer)
    assert row["phone_e164"] == e164
    secret = get_settings().secret_key.get_secret_value()
    assert bytes(row["otp_hash"]) == keyed_digest(secret, "phone_otp", f"{body['verification_id']}:{code}")
    assert bytes(row["otp_hash"]) != hashlib.sha256(code.encode()).digest()

    confirmed = await confirm(developer, body["verification_id"], f"{code[:3]} {code[3:]}")  # spaces are fine
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json() == {"verification_level": "d1"}
    assert await level_of(developer) == "d1"
    assert (await code_row(owner_engine, body["verification_id"]))["verified_at"] is not None

    again = await confirm(developer, body["verification_id"], code)
    assert (again.status_code, again.json()["detail"]["code"]) == (409, "already_verified")
    another = await ask(developer, new_number()[0])
    assert (another.status_code, another.json()["detail"]["code"]) == (409, "already_verified")

    async with owner_engine.connect() as conn:
        events = (
            await conn.execute(
                text("SELECT action, payload FROM audit_events WHERE actor_user_id = :u ORDER BY seq"),
                {"u": user_of(developer)},
            )
        ).all()
    assert [e.action for e in events] == ["verification.phone_code_sent", "verification.phone_verified"]
    assert all(len(e.payload["phone_digest"]) == 64 for e in events)


async def test_five_wrong_codes_lock_the_code(signed_in: Client, owner_engine: AsyncEngine) -> None:
    developer = await signed_in()
    sent = (await ask(developer, new_number()[0])).json()
    right = last_code(developer)
    wrong = f"{(int(right) + 1) % 1_000_000:06d}"
    for left in (4, 3, 2, 1):
        refused = await confirm(developer, sent["verification_id"], wrong)
        assert refused.status_code == 400
        assert refused.json()["detail"]["code"] == "invalid_code"
        assert refused.json()["detail"]["attempts_left"] == left
    fifth = await confirm(developer, sent["verification_id"], wrong)
    assert (fifth.status_code, fifth.json()["detail"]["code"]) == (429, "code_locked")
    late = await confirm(developer, sent["verification_id"], right)
    assert (late.status_code, late.json()["detail"]["code"]) == (429, "code_locked")
    assert (await code_row(owner_engine, sent["verification_id"]))["attempts"] == 5
    assert await level_of(developer) == "d0"


async def test_a_malformed_code_is_422_and_not_counted(signed_in: Client, owner_engine: AsyncEngine) -> None:
    developer = await signed_in()
    sent = (await ask(developer, new_number()[0])).json()
    for bad in ("12345a", "1234567", "12 34 5"):
        response = await confirm(developer, sent["verification_id"], bad)
        assert (response.status_code, response.json()["detail"]["code"]) == (422, "invalid_code_format")
    assert (await code_row(owner_engine, sent["verification_id"]))["attempts"] == 0


async def test_an_expired_code_is_refused(
    signed_in: Client, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    developer = await signed_in()
    sent = (await ask(developer, new_number()[0])).json()
    at(monkeypatch, bridge.clock.utcnow() + timedelta(minutes=10, seconds=1))
    response = await confirm(developer, sent["verification_id"], last_code(developer))
    assert (response.status_code, response.json()["detail"]["code"]) == (400, "code_expired")
    assert (await code_row(owner_engine, sent["verification_id"]))["attempts"] == 0
    assert await level_of(developer) == "d0"


async def test_the_database_clock_decides_expiry(
    signed_in: Client, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when the application clock says the code is fresh, app_confirm_phone_otp refuses an expired one."""
    developer = await signed_in()
    sent = (await ask(developer, new_number()[0])).json()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE phone_verifications SET expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": sent["verification_id"]},
        )
    at(monkeypatch, bridge.clock.utcnow() - timedelta(hours=1))
    response = await confirm(developer, sent["verification_id"], last_code(developer))
    assert (response.status_code, response.json()["detail"]["code"]) == (400, "code_expired")
    assert (await code_row(owner_engine, sent["verification_id"]))["attempts"] == 0
    assert await level_of(developer) == "d0"


async def test_another_user_cannot_confirm(signed_in: Client, owner_engine: AsyncEngine) -> None:
    owner, stranger = await signed_in(), await signed_in()
    sent = (await ask(owner, new_number()[0])).json()
    code = last_code(owner)
    response = await confirm(stranger, sent["verification_id"], code)
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
    assert (await code_row(owner_engine, sent["verification_id"]))["attempts"] == 0
    assert await level_of(stranger) == "d0"
    assert (await confirm(owner, sent["verification_id"], code)).status_code == 200
    unknown = await confirm(owner, str(uuid7()), code)
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "not_found")


# --------------------------------------------------------------------------------------------------- throttling


async def test_resends_are_throttled_per_user(signed_in: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    developer = await signed_in()
    start = bridge.clock.utcnow()
    typed, _ = new_number()

    async def ask_at(offset: timedelta) -> httpx.Response:
        at(monkeypatch, start + offset)
        return await ask(developer, typed)

    assert (await ask_at(timedelta(0))).status_code == 201
    too_soon = await ask_at(timedelta(seconds=30))
    assert (too_soon.status_code, too_soon.json()["detail"]["code"]) == (429, "resend_too_soon")
    assert too_soon.json()["detail"]["retry_after_seconds"] == 60
    assert (await ask_at(timedelta(seconds=61))).status_code == 201
    assert (await ask_at(timedelta(seconds=122))).status_code == 201
    window = await ask_at(timedelta(seconds=183))  # three codes in 15 minutes
    assert (window.status_code, window.json()["detail"]["code"]) == (429, "too_many_codes")
    assert (await ask_at(timedelta(minutes=16))).status_code == 201
    assert (await ask_at(timedelta(minutes=17, seconds=30))).status_code == 201
    daily = await ask_at(timedelta(minutes=40))  # five codes a day
    assert (daily.status_code, daily.json()["detail"]["code"]) == (429, "too_many_codes")
    assert len(sms_outbox(developer).outbox) == 5


async def test_concurrent_requests_from_one_account_send_one_code(signed_in: Client) -> None:
    """The profile row is locked while the throttle is checked, so two racing requests cannot both pass it."""
    developer = await signed_in()
    typed, _ = new_number()
    responses = await asyncio.gather(ask(developer, typed), ask(developer, typed))
    assert sorted(r.status_code for r in responses) == [201, 429]
    assert len(sms_outbox(developer).outbox) == 1


async def test_one_number_is_throttled_across_accounts(signed_in: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    typed, _ = new_number()
    start = bridge.clock.utcnow()
    for n in range(3):
        at(monkeypatch, start + timedelta(seconds=n))
        assert (await ask(await signed_in(), typed)).status_code == 201
    fourth = await ask(await signed_in(), typed)
    assert (fourth.status_code, fourth.json()["detail"]["code"]) == (429, "too_many_codes")


async def test_one_ip_is_throttled_across_accounts(signed_in: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verification, "IP_SENDS_PER_WINDOW", 2)
    first = await signed_in()
    ip = first.headers["X-Forwarded-For"]
    clients = [first, await signed_in(), await signed_in()]
    for client in clients:
        client.headers["X-Forwarded-For"] = ip
    assert (await ask(clients[0], new_number()[0])).status_code == 201
    assert (await ask(clients[1], new_number()[0])).status_code == 201
    third = await ask(clients[2], new_number()[0])
    assert (third.status_code, third.json()["detail"]["code"]) == (429, "too_many_codes")


# ------------------------------------------------------------------------------------------------ refusals, privacy


@pytest.mark.parametrize("phone", ["+255712345678", "0201234567", "0712 345 67", "+1 415 555 0123"])
async def test_numbers_that_are_not_kenyan_mobiles_are_422(signed_in: Client, phone: str) -> None:
    developer = await signed_in()
    response = await ask(developer, phone)
    assert (response.status_code, response.json()["detail"]["code"]) == (422, "invalid_phone")
    assert sms_outbox(developer).outbox == []


async def test_accounts_without_a_developer_profile_get_404(signed_in: Client) -> None:
    org_person = await signed_in(developer=False)
    response = await ask(org_person, new_number()[0])
    assert response.status_code == 404
    assert sms_outbox(org_person).outbox == []


async def test_the_number_and_text_stay_out_of_logs_and_audit_events(
    signed_in: Client,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    developer = await signed_in()
    typed, e164 = new_number()
    fake: FakeSmsProvider = sms_outbox(developer)
    fake.fail_next(SmsError("Africa's Talking status 403 (InvalidPhoneNumber)", code=403))
    start = bridge.clock.utcnow()
    with capture_logs() as logs:
        failed = await ask(developer, typed)
        assert (failed.status_code, failed.json()["detail"]["code"]) == (503, "sms_unavailable")
        at(monkeypatch, start + timedelta(seconds=61))
        sent = (await ask(developer, typed)).json()
        code = last_code(developer)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        assert (await confirm(developer, sent["verification_id"], wrong)).status_code == 400
        assert (await confirm(developer, sent["verification_id"], code)).status_code == 200
    out, err = capfd.readouterr()

    events = {entry["event"] for entry in logs}
    assert {"verification.sms_failed", "verification.sms_sent"} <= events
    async with owner_engine.connect() as conn:
        audit = (
            await conn.execute(
                text(
                    "SELECT e.action, e.payload::text AS payload, coalesce(d.details::text, '') AS details"
                    " FROM audit_events e LEFT JOIN event_details d ON d.event_id = e.id"
                    " WHERE e.actor_user_id = :u"
                ),
                {"u": user_of(developer)},
            )
        ).all()
    assert [a.action for a in audit].count("verification.phone_code_failed") == 1
    national = "0" + e164[4:]
    haystacks = [repr(logs), out, err, *(a.payload + a.details for a in audit)]
    for secret in (e164, e164[1:], national, e164[4:], code, fake.outbox[-1].text):
        for haystack in haystacks:
            assert secret not in haystack
