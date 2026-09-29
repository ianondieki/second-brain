"""Synthetic cassettes replayed through the real SDK (D-18: no paid calls; AC-SEC-5: no network in CI).

A cassette is a hand-written JSON file marked ``"synthetic": true`` holding ordered HTTP interactions (method, path,
status and a ``json`` body or ``jsonl`` lines). ``CassettePlayer`` serves them through an ``httpx2.MockTransport``
to ``AnthropicAdapter``, so the adapter's request building and the SDK's response parsing both run; every request
the SDK sends is kept in ``requests`` for assertions (for example that a Tier-2 value never left, AC-SEC-6).
Unit tests and the cassette evals (``backend/tests/evals/``) use it; recorded real traffic is never stored.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
from pydantic import SecretStr

from bridge.llm.anthropic_adapter import AnthropicAdapter

SYNTHETIC_KEY = SecretStr("synthetic-cassette-key-not-a-real-credential")


class CassetteError(AssertionError):
    """The cassette is not synthetic, is exhausted, or does not match the request the SDK sent."""


@dataclass(frozen=True, slots=True)
class Interaction:
    method: str
    path: str
    status: int
    body: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    path: str
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


def _interaction(raw: dict[str, Any]) -> Interaction:
    request, response = raw["request"], raw["response"]
    if "jsonl" in response:
        body = "".join(json.dumps(line) + "\n" for line in response["jsonl"]).encode()
        content_type = "application/binary"
    else:
        body = json.dumps(response["json"]).encode()
        content_type = "application/json"
    return Interaction(
        str(request["method"]).upper(), str(request["path"]), int(response["status"]), body, content_type
    )


def load(path: Path) -> list[Interaction]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic") is not True:
        raise CassetteError(f"{path.name} is not marked synthetic: only hand-written cassettes are allowed (D-18)")
    return [_interaction(raw) for raw in data["interactions"]]


class CassettePlayer:
    def __init__(self, interactions: Iterable[Interaction]) -> None:
        self._queue: deque[Interaction] = deque(interactions)
        self.requests: list[RecordedRequest] = []
        self.errors: list[CassetteError] = []  # kept here: the adapter raises provider errors from None

    @classmethod
    def from_files(cls, *paths: Path) -> CassettePlayer:
        return cls(interaction for path in paths for interaction in load(path))

    @property
    def exhausted(self) -> bool:
        return not self._queue

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(RecordedRequest(request.method, request.url.path, request.content))
        if not self._queue:
            return self._fail(f"cassette exhausted at {request.method} {request.url.path}")
        expected = self._queue.popleft()
        if (expected.method, expected.path) != (request.method, request.url.path):
            return self._fail(
                f"cassette expected {expected.method} {expected.path}, got {request.method} {request.url.path}"
            )
        return httpx2.Response(expected.status, content=expected.body, headers={"content-type": expected.content_type})

    def _fail(self, message: str) -> httpx2.Response:
        error = CassetteError(message)
        self.errors.append(error)
        raise error

    def adapter(self) -> AnthropicAdapter:
        """An ``AnthropicAdapter`` whose only transport is this cassette (no SDK retries)."""
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))
        return AnthropicAdapter(api_key=SYNTHETIC_KEY, timeout_seconds=5.0, max_retries=0, http_client=client)
