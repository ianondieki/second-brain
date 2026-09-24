"""REQ-NOT-01: the Postmark adapter, against respx fakes only (AC-SEC-5: no test reaches api.postmarkapp.com).

Request fields, response fields and error codes are from Postmark's official docs, read 2026-09-24:
https://postmarkapp.com/developer/api/email-api (Send a single email) and
https://postmarkapp.com/developer/api/overview (HTTP response codes, API error codes).
Classification follows ``reminder/notify.py``: network errors, timeouts, 429 and 5xx are transient; other 4xx are
permanent.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from bridge.notifications.email import DeliveryError, EmailMessage, PostmarkEmailProvider, SendResult

URL = "https://api.postmarkapp.com/email"
TOKEN = "pm-unit-test-token-not-real"
SENDER = "Bridge <no-reply@bridge.test>"
ADDRESS = "dev@example.com"
MESSAGE_ID = "0a129aee-e1cd-480d-b08d-4f48548ff48d"


def provider(**overrides: Any) -> PostmarkEmailProvider:
    values: dict[str, Any] = {"server_token": SecretStr(TOKEN), "sender": SENDER, "message_stream": "outbound"}
    values.update(overrides)
    return PostmarkEmailProvider(**values)


def message(**overrides: Any) -> EmailMessage:
    values: dict[str, Any] = {"to": ADDRESS, "subject": "Your proposal", "text": "Hello"}
    values.update(overrides)
    return EmailMessage(**values)


def accepted() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "To": ADDRESS,
            "SubmittedAt": "2026-09-24T07:25:01.4178645-05:00",
            "MessageID": MESSAGE_ID,
            "ErrorCode": 0,
            "Message": "OK",
        },
    )


async def send_expecting_error(response: httpx.Response | Exception) -> DeliveryError:
    with respx.mock(assert_all_called=True) as router:
        if isinstance(response, Exception):
            router.post(URL).mock(side_effect=response)
        else:
            router.post(URL).mock(return_value=response)
        with pytest.raises(DeliveryError) as info:
            await provider().send(message())
    error = info.value
    assert TOKEN not in str(error)
    assert ADDRESS not in str(error)
    return error


async def test_send_posts_the_documented_fields_and_returns_the_message_id() -> None:
    full = message(
        html="<p>Hello</p>",
        tag="em2",
        headers={
            "List-Unsubscribe": "<https://bridge.test/u/1>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    with respx.mock(assert_all_called=True) as router:
        route = router.post(URL).mock(return_value=accepted())
        result = await provider(message_stream="broadcast").send(full)

    assert result == SendResult(provider="postmark", message_id=MESSAGE_ID)
    request = route.calls.last.request
    assert request.headers["X-Postmark-Server-Token"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Content-Type"] == "application/json"
    assert json.loads(request.content) == {
        "From": SENDER,
        "To": ADDRESS,
        "Subject": "Your proposal",
        "TextBody": "Hello",
        "HtmlBody": "<p>Hello</p>",
        "Tag": "em2",
        "Headers": [
            {"Name": "List-Unsubscribe", "Value": "<https://bridge.test/u/1>"},
            {"Name": "List-Unsubscribe-Post", "Value": "List-Unsubscribe=One-Click"},
        ],
        "MessageStream": "broadcast",
        "TrackOpens": False,
        "TrackLinks": "None",
    }


async def test_a_text_only_untagged_message_omits_the_optional_fields() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(URL).mock(return_value=accepted())
        await provider().send(message())
    body = json.loads(route.calls.last.request.content)
    assert "HtmlBody" not in body
    assert "Tag" not in body
    assert "Headers" not in body
    assert body["MessageStream"] == "outbound"


async def test_an_injected_client_and_base_url_are_used() -> None:
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=True) as router:
            route = router.post("http://postmark.fake/email").mock(return_value=accepted())
            result = await provider(client=client, base_url="http://postmark.fake").send(message())
    assert result.message_id == MESSAGE_ID
    assert route.called


@pytest.mark.parametrize(
    ("status", "body", "transient", "code"),
    [
        pytest.param(
            422,
            {
                "ErrorCode": 406,
                "Message": f"You tried to send to recipient(s) that have been marked as inactive: {ADDRESS}",
            },
            False,
            406,
            id="422-406-inactive-recipient",
        ),
        pytest.param(
            422, {"ErrorCode": 300, "Message": f"Invalid 'To' address: '{ADDRESS}'."}, False, 300, id="422-300-invalid"
        ),
        pytest.param(422, {"ErrorCode": 403, "Message": "Invalid request field(s): 'From'."}, False, 403, id="422-403"),
        pytest.param(422, {"ErrorCode": 1235, "Message": "The stream does not exist."}, False, 1235, id="422-1235"),
        pytest.param(422, {"ErrorCode": 412, "Message": "Account pending approval."}, False, 412, id="422-412"),
        pytest.param(401, {"ErrorCode": 10, "Message": "Bad or missing Server API token."}, False, 10, id="401-10"),
        pytest.param(404, None, False, None, id="404-no-body"),
        pytest.param(413, None, False, None, id="413-payload-too-large"),
        pytest.param(415, None, False, None, id="415-unsupported-media-type"),
        pytest.param(429, None, True, None, id="429-rate-limited"),
        pytest.param(500, {"ErrorCode": 101, "Message": "Unexpected error."}, True, 101, id="500-101"),
        pytest.param(503, {"ErrorCode": 100, "Message": "Offline for maintenance."}, True, 100, id="503-100"),
        pytest.param(502, "<html>Bad gateway</html>", True, None, id="502-html-from-a-proxy"),
        pytest.param(504, None, True, None, id="504-gateway-timeout"),
    ],
)
async def test_http_errors_are_classified(status: int, body: object, transient: bool, code: int | None) -> None:
    if body is None:
        response = httpx.Response(status)
    elif isinstance(body, str):
        response = httpx.Response(status, text=body)
    else:
        response = httpx.Response(status, json=body)
    error = await send_expecting_error(response)
    assert error.transient is transient
    assert error.code == code
    assert str(status) in str(error)


async def test_the_api_error_code_header_is_used_when_the_body_has_none() -> None:
    # Postmark echoes ErrorCode in the X-PM-ApiErrorCode response header (overview, API error codes).
    error = await send_expecting_error(httpx.Response(422, text="not json", headers={"X-PM-ApiErrorCode": "406"}))
    assert error.transient is False
    assert error.code == 406


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(httpx.ConnectError("connection refused"), id="connect-error"),
        pytest.param(httpx.ConnectTimeout("timed out"), id="connect-timeout"),
        pytest.param(httpx.ReadTimeout("timed out"), id="read-timeout"),
        pytest.param(httpx.WriteTimeout("timed out"), id="write-timeout"),
        pytest.param(httpx.PoolTimeout("timed out"), id="pool-timeout"),
        pytest.param(httpx.RemoteProtocolError("server hung up"), id="remote-protocol-error"),
        pytest.param(httpx.ReadError("reset"), id="read-error"),
    ],
)
async def test_network_errors_and_timeouts_are_transient(error: Exception) -> None:
    delivery_error = await send_expecting_error(error)
    assert delivery_error.transient is True
    assert delivery_error.code is None


async def test_an_unreadable_success_body_is_transient() -> None:
    # Ported from reminder/notify.py: a 200 with a body that is not JSON (e.g. a captive portal) is retried.
    error = await send_expecting_error(httpx.Response(200, text="<html>hotel wifi</html>"))
    assert error.transient is True


async def test_a_success_status_with_an_error_code_is_permanent() -> None:
    error = await send_expecting_error(httpx.Response(200, json={"ErrorCode": 406, "Message": "Inactive recipient"}))
    assert error.transient is False
    assert error.code == 406


async def test_a_success_without_a_message_id_is_permanent() -> None:
    # Ported from reminder/notify.py: "accepted the call but returned no message id".
    error = await send_expecting_error(httpx.Response(200, json={"ErrorCode": 0, "Message": "OK"}))
    assert error.transient is False


@pytest.mark.parametrize("token", [SecretStr(""), SecretStr("   ")])
def test_a_missing_token_fails_closed(token: SecretStr) -> None:
    with pytest.raises(ValueError, match="POSTMARK_SERVER_TOKEN"):
        provider(server_token=token)


def test_the_token_never_appears_in_the_provider_repr() -> None:
    assert TOKEN not in repr(provider())
    assert TOKEN not in repr(vars(provider()))
