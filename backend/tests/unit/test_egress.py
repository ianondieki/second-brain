"""AC-SEC-5 (make check side): tests cannot open connections to real providers."""

from __future__ import annotations

import os
import socket
import urllib.request
from collections.abc import Iterator

import httpcore
import httpx
import pytest

from tests import egress
from tests.egress import EgressBlockedError

PROVIDER_URL = "https://api.africastalking.com/version1/messaging"
EXTERNAL_IP_URL = "https://1.1.1.1/"  # an IP literal: the guard decides, not the resolver
LOOPBACK_PROXY = "http://127.0.0.1:9"
PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")  # and their lowercase forms


@pytest.mark.parametrize(
    "host", ["api.anthropic.com", "api.postmarkapp.com", "graph.facebook.com", "api.paystack.co", "8.8.8.8"]
)
def test_provider_connections_are_blocked(host: str) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        with pytest.raises((EgressBlockedError, OSError)):
            sock.connect((host, 443))


def test_blocked_error_is_raised_before_any_packet() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock, pytest.raises(EgressBlockedError):
        sock.connect(("1.1.1.1", 443))


def test_loopback_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2):
            pass


# ------------------------------------------------------------------ proxies: loopback is allowed, so none may be set


def routes_through_a_proxy(client: httpx.AsyncClient, url: str) -> bool:
    """Whether ``client`` would send a request for ``url`` to a proxy rather than connect to its host."""
    transport = client._transport_for_url(httpx.URL(url))
    pool = getattr(transport, "_pool", None)
    return transport is not client._transport or isinstance(pool, (httpcore.AsyncHTTPProxy, httpcore.AsyncSOCKSProxy))


def causes(exc: BaseException) -> Iterator[BaseException]:
    """``exc``, its causes and contexts, and the members of any exception group among them."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)


def proxy_variables() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name.lower().endswith("_proxy")}


def test_no_proxy_is_configured_for_the_tests() -> None:
    """The conftest drops every proxy variable before any test runs and sets ``NO_PROXY=*``: a loopback proxy (a
    developer's, or a cloud container's ``HTTPS_PROXY=http://127.0.0.1:...``) passes the loopback-only guard and would
    reach any host on a test's behalf. ``NO_PROXY=*`` also stops urllib (which httpx asks) from falling back to the
    Windows registry or macOS system proxy settings when the environment names none."""
    assert {name.upper(): value for name, value in proxy_variables().items()} == {"NO_PROXY": "*"}
    assert set(urllib.request.getproxies()) <= {"no"}


async def test_httpx_connects_directly_and_the_guard_refuses_an_external_host() -> None:
    async with httpx.AsyncClient() as client:
        assert not routes_through_a_proxy(client, PROVIDER_URL)
        assert not routes_through_a_proxy(client, EXTERNAL_IP_URL)
        with pytest.raises(httpx.ConnectError) as refused:
            await client.get(EXTERNAL_IP_URL)
    assert any(isinstance(cause, EgressBlockedError) for cause in causes(refused.value))


async def test_disabling_proxies_removes_the_route_around_the_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*PROXY_VARIABLES, "SOCKS_PROXY"):
        value = "" if name == "NO_PROXY" else LOOPBACK_PROXY
        monkeypatch.setenv(name, value)
        monkeypatch.setenv(name.lower(), value)
    async with httpx.AsyncClient() as proxied:
        assert routes_through_a_proxy(proxied, PROVIDER_URL)  # what a loopback proxy variable does to every client

    dropped = egress.disable_proxies()

    assert {name.upper() for name in dropped} == {*PROXY_VARIABLES, "SOCKS_PROXY"}
    assert {name.upper(): value for name, value in proxy_variables().items()} == {"NO_PROXY": "*"}
    async with httpx.AsyncClient() as direct:
        assert not routes_through_a_proxy(direct, PROVIDER_URL)
        with pytest.raises(httpx.ConnectError) as refused:
            await direct.get(EXTERNAL_IP_URL)
    assert any(isinstance(cause, EgressBlockedError) for cause in causes(refused.value))
