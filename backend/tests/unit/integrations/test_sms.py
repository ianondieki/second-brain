"""REQ-PROV-04: the ``SmsProvider`` seam for D1 phone codes (docs/spec/06 6.4 item 8).

The Africa's Talking adapter is exercised against respx fakes only: no test reaches api.africastalking.com
(AC-SEC-5; the egress guard refuses it anyway). Request and response fields follow Africa's Talking's SMS API
documentation (``POST /version1/messaging``, form-encoded, ``apiKey`` header, ``SMSMessageData.Recipients``); they are
confirmed against the live account at gate G1.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from bridge.config import AppEnv, Settings
from bridge.integrations.sms import (
    AT_LIVE_URL,
    AT_SANDBOX_URL,
    AfricasTalkingSmsProvider,
    FakeSmsProvider,
    SmsError,
    SmsMessage,
    SmsResult,
    redact_phones,
    sms_provider_from_settings,
)

PHONE = "+254712345678"
TEXT = "123456 is your Bridge code. It expires in 10 minutes."
API_KEY = "at-unit-test-key-not-real"
MESSAGE_ID = "ATXid_0f1e2d3c4b5a"


def message(**overrides: Any) -> SmsMessage:
    values: dict[str, Any] = {"to": PHONE, "text": TEXT}
    values.update(overrides)
    return SmsMessage(**values)


def provider(**overrides: Any) -> AfricasTalkingSmsProvider:
    values: dict[str, Any] = {"username": "bridge-live", "api_key": SecretStr(API_KEY), "sender_id": "BRIDGE"}
    values.update(overrides)
    return AfricasTalkingSmsProvider(**values)


def recipient(status_code: int = 101, status: str = "Success", **extra: Any) -> dict[str, Any]:
    return {"statusCode": status_code, "number": PHONE, "status": status, "cost": "KES 0.8000", **extra}


def accepted(**extra: Any) -> httpx.Response:
    entry = recipient(messageId=MESSAGE_ID, **extra)
    summary = f"Sent to 1/1 Total Cost: KES 0.8000 ({PHONE})"
    return httpx.Response(201, json={"SMSMessageData": {"Message": summary, "Recipients": [entry]}})


async def send_expecting_error(response: httpx.Response | Exception, *, url: str = AT_LIVE_URL) -> SmsError:
    with respx.mock(assert_all_called=True) as router:
        if isinstance(response, Exception):
            router.post(url).mock(side_effect=response)
        else:
            router.post(url).mock(return_value=response)
        with pytest.raises(SmsError) as info:
            await provider().send(message())
    error = info.value
    for secret in (API_KEY, PHONE, "712345678", TEXT, "123456"):
        assert secret not in str(error)
    return error


# ------------------------------------------------------------------------------------------------------ SmsMessage


@pytest.mark.parametrize("to", ["0712345678", "254712345678", "+0712345678", "+2547", "+254 712 345 678", ""])
def test_a_message_needs_an_e164_recipient(to: str) -> None:
    with pytest.raises(ValueError, match=r"E\.164"):
        message(to=to)


@pytest.mark.parametrize("text", ["", "x" * 161, "line one\nline two", "Karibu — code 123456", "\x00"])
def test_a_message_is_one_short_printable_ascii_line(text: str) -> None:
    with pytest.raises(ValueError, match="160 printable ASCII"):
        message(text=text)


def test_a_message_never_shows_its_number_or_text() -> None:
    shown = repr(message()) + str(message())
    assert PHONE not in shown
    assert TEXT not in shown
    assert "123456" not in shown


def test_redact_phones_hides_numbers_in_any_common_form() -> None:
    text = "Refused +254712345678, 0712 345 678 and 254-712-345-678; balance KES 0.80, ref 42."
    redacted = redact_phones(text)
    assert "712" not in redacted
    assert redacted.count("[phone]") == 3
    assert "KES 0.80, ref 42" in redacted
    assert len(redact_phones("x" * 1000, limit=50)) == 50


# ------------------------------------------------------------------------------------------------------------ Fake


async def test_the_fake_records_messages_in_order() -> None:
    fake = FakeSmsProvider()
    first = await fake.send(message())
    second = await fake.send(message(to="+254112345678"))
    assert fake.name == "fake"
    assert (first, second) == (SmsResult("fake", "fake-sms-1"), SmsResult("fake", "fake-sms-2"))
    assert [m.to for m in fake.outbox] == [PHONE, "+254112345678"]
    assert fake.attempts == 2


async def test_the_fake_raises_scripted_failures_once_each_in_order() -> None:
    fake = FakeSmsProvider(failures=[SmsError("down", transient=True)])
    fake.fail_next(SmsError("refused", code=403))
    with pytest.raises(SmsError, match="down"):
        await fake.send(message())
    with pytest.raises(SmsError, match="refused") as info:
        await fake.send(message())
    assert info.value.code == 403
    assert info.value.transient is False
    await fake.send(message())
    assert fake.attempts == 3
    assert len(fake.outbox) == 1


# ------------------------------------------------------------------------------------------ Africa's Talking adapter


async def test_send_posts_the_documented_form_and_returns_the_message_id() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(AT_LIVE_URL).mock(return_value=accepted())
        result = await provider().send(message())
    assert result == SmsResult(provider="africastalking", message_id=MESSAGE_ID)
    request = route.calls.last.request
    assert request.headers["apiKey"] == API_KEY
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "username": ["bridge-live"],
        "to": [PHONE],
        "message": [TEXT],
        "from": ["BRIDGE"],
    }


async def test_without_a_sender_id_the_from_field_is_omitted() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(AT_LIVE_URL).mock(return_value=accepted())
        await provider(sender_id=None).send(message())
    assert "from" not in parse_qs(route.calls.last.request.content.decode())


async def test_the_sandbox_account_uses_the_sandbox_endpoint() -> None:
    sandbox = provider(username="sandbox")
    assert sandbox.is_sandbox
    assert not provider().is_sandbox
    with respx.mock(assert_all_called=True) as router:
        route = router.post(AT_SANDBOX_URL).mock(return_value=accepted())
        await sandbox.send(message())
    assert route.called


async def test_an_injected_client_and_base_url_are_used() -> None:
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=True) as router:
            route = router.post("http://at.fake/version1/messaging").mock(return_value=accepted())
            result = await provider(client=client, base_url="http://at.fake/version1/messaging").send(message())
    assert result.message_id == MESSAGE_ID
    assert route.called


@pytest.mark.parametrize("status_code", [100, 101, 102])
async def test_processed_sent_and_queued_all_count_as_accepted(status_code: int) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(AT_LIVE_URL).mock(return_value=accepted(statusCode=status_code))
        assert (await provider().send(message())).message_id == MESSAGE_ID


@pytest.mark.parametrize(
    ("status_code", "status", "transient"),
    [
        pytest.param(401, "RiskHold", False, id="401-risk-hold"),
        pytest.param(402, "InvalidSenderId", False, id="402-sender-id"),
        pytest.param(403, "InvalidPhoneNumber", False, id="403-invalid-number"),
        pytest.param(404, "UnsupportedNumberType", False, id="404-number-type"),
        pytest.param(405, "InsufficientBalance", False, id="405-balance"),
        pytest.param(406, "UserInBlacklist", False, id="406-blacklist"),
        pytest.param(407, "CouldNotRoute", False, id="407-route"),
        pytest.param(409, "DoNotDisturbRejection", False, id="409-dnd"),
        pytest.param(500, "InternalServerError", True, id="500-internal"),
        pytest.param(501, "GatewayError", True, id="501-gateway"),
        pytest.param(502, "RejectedByGateway", False, id="502-rejected"),
    ],
)
async def test_a_refused_recipient_is_classified_by_its_status_code(
    status_code: int, status: str, transient: bool
) -> None:
    body = {"SMSMessageData": {"Message": "Sent to 0/1", "Recipients": [recipient(status_code, status)]}}
    error = await send_expecting_error(httpx.Response(201, json=body))
    assert error.code == status_code
    assert error.transient is transient
    assert status in str(error)


@pytest.mark.parametrize(
    ("status", "transient"),
    [(401, False), (400, False), (429, True), (500, True), (503, True)],
)
async def test_http_errors_are_permanent_except_429_and_5xx(status: int, transient: bool) -> None:
    error = await send_expecting_error(httpx.Response(status, text=f"The request for {PHONE} was refused"))
    assert error.code == status
    assert error.transient is transient
    assert f"HTTP {status}" in str(error)


@pytest.mark.parametrize(
    "exc", [httpx.ConnectError("no route to 0712345678"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("x")]
)
async def test_network_failures_are_transient(exc: Exception) -> None:
    error = await send_expecting_error(exc)
    assert error.transient is True
    assert "unreachable" in str(error)


async def test_a_success_status_with_an_unreadable_body_is_transient() -> None:
    error = await send_expecting_error(httpx.Response(201, text="<html>portal</html>"))
    assert error.transient is True


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"SMSMessageData": {"Message": f"InvalidPhoneNumber {PHONE}", "Recipients": []}}, id="none"),
        pytest.param({"SMSMessageData": {"Recipients": ["oops"]}}, id="not-an-object"),
        pytest.param({"SMSMessageData": "oops"}, id="no-data"),
        pytest.param({"unexpected": True}, id="other-json"),
        pytest.param(["a", "list"], id="json-list"),
    ],
)
async def test_a_reply_without_a_recipient_is_a_permanent_error(body: Any) -> None:
    error = await send_expecting_error(httpx.Response(201, json=body))
    assert error.transient is False
    assert "no recipient" in str(error)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"status": "Success", "messageId": MESSAGE_ID}, id="no-status-code"),
        pytest.param({"statusCode": True, "messageId": MESSAGE_ID}, id="boolean-status-code"),
        pytest.param({"statusCode": 101, "status": "Success"}, id="no-message-id"),
        pytest.param({"statusCode": 101, "messageId": ""}, id="empty-message-id"),
    ],
)
async def test_an_incomplete_recipient_entry_is_a_permanent_error(entry: dict[str, Any]) -> None:
    body = {"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [entry]}}
    error = await send_expecting_error(httpx.Response(201, json=body))
    assert error.transient is False


def test_the_adapter_needs_its_username_and_key_and_never_shows_the_key() -> None:
    with pytest.raises(ValueError, match="AFRICASTALKING_USERNAME"):
        provider(username=" ")
    with pytest.raises(ValueError, match="AFRICASTALKING_API_KEY"):
        provider(api_key=SecretStr(""))
    assert API_KEY not in repr(provider())


# ------------------------------------------------------------------------------------------------------- Selection

GOOD = "x" * 32


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr(GOOD),
        "recovery_code_pepper": SecretStr("p" * 32),
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def live_settings(app_env: AppEnv = "production", username: str = "bridge-live") -> Settings:
    return settings(
        app_env=app_env,
        email_provider="postmark" if app_env == "production" else "smtp",
        postmark_server_token=SecretStr("pm-test-token"),
        public_base_url="https://bridge.test",
        sms_provider="africastalking",
        africastalking_username=username,
        africastalking_api_key=SecretStr(API_KEY),
        africastalking_sender_id="BRIDGE",
    )


def test_the_fake_is_the_default_for_dev_and_test() -> None:
    assert settings().sms_provider == "fake"
    for app_env in ("dev", "test", "staging"):
        assert isinstance(sms_provider_from_settings(settings(app_env=app_env)), FakeSmsProvider)


@pytest.mark.parametrize("app_env", ["dev", "staging", "production"])
def test_africas_talking_is_built_with_its_credentials(app_env: AppEnv) -> None:
    built = sms_provider_from_settings(live_settings(app_env))
    assert isinstance(built, AfricasTalkingSmsProvider)
    assert built.name == "africastalking"


def test_settings_refuse_africas_talking_without_credentials() -> None:
    with pytest.raises(ValidationError, match="AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY"):
        settings(sms_provider="africastalking", africastalking_username="bridge-live")
    with pytest.raises(ValidationError, match="AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY"):
        settings(sms_provider="africastalking", africastalking_api_key=SecretStr(API_KEY))


def test_selection_refuses_africas_talking_without_credentials() -> None:
    built = settings(app_env="dev")
    built.sms_provider = "africastalking"  # plain assignment is not re-validated, so this reaches the selection
    with pytest.raises(ValueError, match="AFRICASTALKING_USERNAME and AFRICASTALKING_API_KEY"):
        sms_provider_from_settings(built)


def test_tests_and_ci_never_build_the_vendor_adapter() -> None:
    with pytest.raises(ValueError, match="APP_ENV=test"):
        sms_provider_from_settings(live_settings("test"))


def test_production_fails_closed_without_a_real_provider() -> None:
    built = live_settings()
    built.sms_provider = "fake"
    with pytest.raises(ValueError, match="SMS_PROVIDER=fake is not allowed when APP_ENV=production"):
        sms_provider_from_settings(built)
    with pytest.raises(ValueError, match="sandbox"):
        sms_provider_from_settings(live_settings(username="sandbox"))
