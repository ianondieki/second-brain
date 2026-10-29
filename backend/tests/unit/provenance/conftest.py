"""Provenance unit fixtures: one local openssl test TSA per session (tests/openssl_tsa.py)."""

from __future__ import annotations

import pytest

from tests.openssl_tsa import LocalTsa


@pytest.fixture(scope="session")
def local_tsa(tmp_path_factory: pytest.TempPathFactory) -> LocalTsa:
    return LocalTsa.create(tmp_path_factory.mktemp("tsa"))
