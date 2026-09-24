"""Egress guard for the test suite (AC-SEC-5): a test may connect only to loopback, private-network addresses
(Docker services) or Unix sockets. Anything else raises, so no test can reach an LLM, email, WhatsApp or payment
provider even when the machine has network access. CI adds a network-level lock on top (infra/ci/egress-lock.sh).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any

_real_connect: Callable[..., Any] = socket.socket.connect
_real_connect_ex: Callable[..., Any] = socket.socket.connect_ex


class EgressBlockedError(ConnectionRefusedError):
    """Raised when a test tries to open a connection outside loopback or private networks."""


def _is_local(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for *_, addr in infos:
        ip = ipaddress.ip_address(str(addr[0]).split("%")[0])
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return True


def _check(address: Any) -> None:
    if isinstance(address, (str, bytes)):  # Unix domain socket path
        return
    host = str(address[0])
    if not _is_local(host):
        raise EgressBlockedError(f"egress blocked in tests: {host}:{address[1]}")


def _guarded_connect(self: socket.socket, address: Any) -> Any:
    _check(address)
    return _real_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any) -> Any:
    _check(address)
    return _real_connect_ex(self, address)


def install() -> None:
    setattr(socket.socket, "connect", _guarded_connect)  # noqa: B010 - patching a C-level method
    setattr(socket.socket, "connect_ex", _guarded_connect_ex)  # noqa: B010
