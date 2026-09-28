"""REQ-PROV-01 / ADR-007: Tier-2 and provenance key settings are well-formed, come from one source each, and
production accepts KMS only; the in-memory object store never runs in staging or production (fail closed)."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from bridge.config import Settings, decoded_key

KEY = SecretStr(base64.b64encode(bytes(range(32))).decode())
KMS = "arn:aws:kms:af-south-1:000000000000:key/test"


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": KEY,
        "recovery_code_pepper": SecretStr("p" * 32),
        "tier2_local_kek": None,
        "provenance_signing_key": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_keys_are_optional_until_used() -> None:
    settings = make()
    assert settings.tier2_local_kek is None
    assert settings.provenance_signing_key is None
    assert settings.tsa_url.startswith("http")
    assert (settings.s3_bucket_evidence, settings.s3_bucket_kyc_review, settings.s3_bucket_uploads) == (
        "evidence",
        "kyc-review",
        "uploads",
    )


@pytest.mark.parametrize("name", ["tier2_local_kek", "provenance_signing_key"])
@pytest.mark.parametrize("value", ["not base64 at all!!", base64.b64encode(bytes(16)).decode()])
def test_local_keys_must_be_base64_of_32_bytes(name: str, value: str) -> None:
    with pytest.raises(ValidationError, match=f"{name.upper()} must be base64 of exactly 32 bytes"):
        make(**{name: SecretStr(value)})


@pytest.mark.parametrize(
    ("local", "kms"),
    [("tier2_local_kek", "tier2_kms_key_id"), ("provenance_signing_key", "provenance_kms_key_id")],
)
def test_one_key_source_each(local: str, kms: str) -> None:
    with pytest.raises(ValidationError, match="not both"):
        make(**{local: KEY, kms: KMS})


@pytest.mark.parametrize("name", ["tier2_local_kek", "provenance_signing_key"])
def test_production_refuses_local_keys(name: str) -> None:
    with pytest.raises(ValidationError, match="production uses KMS"):
        make(app_env="production", **{name: KEY})


@pytest.mark.parametrize("app_env", ["staging", "production"])
def test_the_memory_object_store_is_for_tests_only(app_env: str) -> None:
    with pytest.raises(ValidationError, match="OBJECT_STORE=memory"):
        make(app_env=app_env, object_store="memory")
    assert make(app_env="test", object_store="memory").object_store == "memory"


def test_decoded_key() -> None:
    assert decoded_key(KEY) == bytes(range(32))
    assert decoded_key(SecretStr("AAAA")) is None
    assert decoded_key(SecretStr("%%%")) is None
