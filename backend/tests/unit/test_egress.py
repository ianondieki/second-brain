"""AC-SEC-5 (make check side): tests cannot open connections to real providers."""

from __future__ import annotations

import socket

import pytest

from tests.egress import EgressBlockedError


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
