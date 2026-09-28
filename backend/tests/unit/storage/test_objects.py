"""Object storage (ADR-007, D-24): the in-memory store for tests and the S3 adapter, exercised through botocore's
Stubber so no request leaves the process (AC-SEC-5)."""

from __future__ import annotations

import base64
import io
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import SecretStr

from bridge.config import Settings
from bridge.storage.objects import (
    InMemoryObjectStore,
    ObjectNotFoundError,
    S3ObjectStore,
    object_store_from_settings,
)

BUCKETS: Any = {"evidence": "bridge-evidence", "kyc-review": "bridge-kyc", "uploads": "bridge-uploads"}


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def stubbed() -> tuple[S3ObjectStore, Stubber]:
    client = boto3.client("s3", region_name="af-south-1", aws_access_key_id="test", aws_secret_access_key="test")
    return S3ObjectStore(BUCKETS, client=client), Stubber(client)


async def test_memory_store_round_trip() -> None:
    store = InMemoryObjectStore()
    await store.put("evidence", "manifests/a/b.json", b"sealed", content_type="application/json")
    assert await store.get("evidence", "manifests/a/b.json") == b"sealed"
    assert store.objects[("evidence", "manifests/a/b.json")][1] == "application/json"
    await store.delete("evidence", "manifests/a/b.json")
    await store.delete("evidence", "manifests/a/b.json")  # idempotent
    with pytest.raises(ObjectNotFoundError):
        await store.get("evidence", "manifests/a/b.json")


@pytest.mark.parametrize(
    ("bucket", "key"), [("backups", "x"), ("evidence", ""), ("evidence", "/abs"), ("evidence", "a/../b")]
)
async def test_unknown_buckets_and_unsafe_keys_are_refused(bucket: Any, key: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - either message
        await InMemoryObjectStore().put(bucket, key, b"x", content_type="text/plain")


async def test_s3_put_get_delete_map_logical_buckets() -> None:
    store, stubber = stubbed()
    stubber.add_response(
        "put_object",
        {},
        {"Bucket": "bridge-evidence", "Key": "m/1.json", "Body": b"sealed", "ContentType": "application/json"},
    )
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(b"sealed"), 6)},
        {"Bucket": "bridge-evidence", "Key": "m/1.json"},
    )
    stubber.add_response("delete_object", {}, {"Bucket": "bridge-kyc", "Key": "r/1"})
    with stubber:
        await store.put("evidence", "m/1.json", b"sealed", content_type="application/json")
        assert await store.get("evidence", "m/1.json") == b"sealed"
        await store.delete("kyc-review", "r/1")
    stubber.assert_no_pending_responses()


async def test_s3_missing_object_and_other_errors() -> None:
    store, stubber = stubbed()
    stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
    stubber.add_client_error("get_object", service_error_code="AccessDenied", http_status_code=403)
    with stubber:
        with pytest.raises(ObjectNotFoundError):
            await store.get("evidence", "missing")
        with pytest.raises(ClientError):
            await store.get("evidence", "forbidden")


def test_s3_client_is_built_lazily_from_settings_without_a_request() -> None:
    store = object_store_from_settings(
        settings(
            s3_endpoint_url="http://127.0.0.1:8333",
            s3_access_key_id=SecretStr("dev"),
            s3_secret_access_key=SecretStr("dev-secret"),
            s3_bucket_evidence="dev-evidence",
        )
    )
    assert isinstance(store, S3ObjectStore)
    assert store.bucket("evidence") == "dev-evidence"
    client = store.client
    assert client is store.client
    assert client.meta.endpoint_url == "http://127.0.0.1:8333"
    assert client.meta.config.s3["addressing_style"] == "path"  # type: ignore[attr-defined]
    aws = object_store_from_settings(settings())
    assert isinstance(aws, S3ObjectStore)
    assert aws.client.meta.region_name == "af-south-1"


def test_memory_store_from_settings() -> None:
    assert isinstance(object_store_from_settings(settings(object_store="memory")), InMemoryObjectStore)
