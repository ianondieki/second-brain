"""Logging (docs/spec/08 Observability; REQ-AUTH-02 fix round 1): the OAuth routes' query strings, which carry the
authorization code, the state and the provider's error text, never reach uvicorn's access log."""

from __future__ import annotations

import asyncio
import io
import logging
import socket
from collections.abc import Iterator

import httpx
import pytest
import uvicorn
from uvicorn.logging import AccessFormatter

from bridge.logging import DropQueryStrings, configure_logging
from bridge.main import create_app

SECRETS = ("4%2F0Aabc-code-secret", "st4te-secret", "provider+error+text")
QUERY = f"code={SECRETS[0]}&state={SECRETS[1]}&error_description={SECRETS[2]}"
ACCESS = logging.getLogger("uvicorn.access")


@pytest.fixture
def access_log() -> Iterator[io.StringIO]:
    """What uvicorn's access logger writes, formatted as uvicorn formats it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    level = ACCESS.level
    ACCESS.addHandler(handler)
    ACCESS.setLevel(logging.INFO)
    yield stream
    ACCESS.removeHandler(handler)
    ACCESS.setLevel(level)


def log_request(path: str) -> None:
    """The call uvicorn's h11 and httptools protocols make after each response."""
    ACCESS.info('%s - "%s %s HTTP/%s" %d', "203.0.113.9:50000", "GET", path, "1.1", 302)


@pytest.mark.parametrize(
    "path", ["/api/auth/oauth/github/callback", "/api/auth/oauth/google/callback", "/api/auth/oauth/github/start"]
)
def test_oauth_query_strings_never_reach_the_access_log(access_log: io.StringIO, path: str) -> None:
    configure_logging()
    log_request(f"{path}?{QUERY}")
    line = access_log.getvalue()
    assert f'"GET {path} HTTP/1.1" 302' in line
    assert not [secret for secret in SECRETS if secret in line]
    assert "?" not in line


def test_other_paths_keep_their_query_string(access_log: io.StringIO) -> None:
    configure_logging()
    log_request("/api/orgs?page=2")
    log_request("/api/auth/oauth/providers")
    assert '"GET /api/orgs?page=2 HTTP/1.1"' in access_log.getvalue()
    assert '"GET /api/auth/oauth/providers HTTP/1.1"' in access_log.getvalue()


def test_the_filter_is_installed_once() -> None:
    configure_logging()
    configure_logging()
    assert len([f for f in ACCESS.filters if isinstance(f, DropQueryStrings)]) == 1


@pytest.mark.parametrize("args", [None, (), ("only",), ("a", "b", 3, "d", 5), ("a", "GET", "/api/auth/oauth/x?c=1")])
def test_records_of_another_shape_pass_unchanged(args: tuple[object, ...] | None) -> None:
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "message", args, None)
    assert DropQueryStrings().filter(record) is True
    assert record.args == args


@pytest.mark.parametrize("http", ["h11", "httptools"])
async def test_a_real_uvicorn_server_logs_oauth_paths_without_their_query(access_log: io.StringIO, http: str) -> None:
    """Guards the record shape the filter relies on against uvicorn upgrades. No provider is configured in unit tests,
    so the callback answers 404 before any database work."""
    app = create_app()  # installs the filter, as in production
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, http=http, log_config=None))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(500):
            if server.started:
                break
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(trust_env=False) as http_client:
            response = await http_client.get(f"http://127.0.0.1:{port}/api/auth/oauth/github/callback?{QUERY}")
        assert response.status_code == 404
    finally:
        server.should_exit = True
        await serving
        sock.close()
    line = access_log.getvalue()
    assert '"GET /api/auth/oauth/github/callback HTTP/1.1" 404' in line
    assert not [secret for secret in SECRETS if secret in line]


@pytest.mark.parametrize(
    ("path", "logged"),
    [
        ("/api/directory/orgs?q=Wanjiku+Kamau&limit=20", "/api/directory/orgs?q=[redacted]&limit=20"),
        ("/api/proposals?niche=solar&q=jane%40example.com", "/api/proposals?niche=solar&q=[redacted]"),
        ("/api/problems?q=", "/api/problems?q=[redacted]"),
        ("/api/problems?faq=kept&q=x&aq=kept", "/api/problems?faq=kept&q=[redacted]&aq=kept"),
    ],
)
def test_search_words_never_reach_the_access_log(access_log: io.StringIO, path: str, logged: str) -> None:
    """P16-E1 item 6 (REQ-SEC-04): what people type in a search box can be a name or an address; the value of ``q``
    is redacted on every path, other parameters stay."""
    configure_logging()
    log_request(path)
    line = access_log.getvalue()
    assert f'"GET {logged} HTTP/1.1" 302' in line
    assert "Wanjiku" not in line
    assert "example.com" not in line
