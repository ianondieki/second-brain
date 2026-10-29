"""Object storage (ADR-007, D-24): the in-memory store for tests and the S3 adapter, exercised through botocore's
Stubber so no request leaves the process (AC-SEC-5)."""

from __future__ import annotations

import base64
import io
import time
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from botocore.response import StreamingBody
from botocore.stub import Stubber
from pydantic import SecretStr

from bridge.config import ConfigurationError, Settings
from bridge.storage import __main__ as storage_cli
from bridge.storage.objects import (
    BucketMissingError,
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


async def test_memory_store_buckets_are_created_once_and_puts_need_them() -> None:
    store = InMemoryObjectStore(buckets_exist=False)
    with pytest.raises(BucketMissingError, match="evidence"):
        await store.put("evidence", "m/1.json", b"x", content_type="application/json")
    with pytest.raises(ConfigurationError, match="evidence, kyc-review, uploads"):
        await store.ensure_buckets(create=False)
    assert await store.ensure_buckets(create=True) == ["evidence", "kyc-review", "uploads"]
    assert await store.ensure_buckets(create=True) == []  # idempotent
    assert await store.ensure_buckets(create=False) == []
    await store.put("evidence", "m/1.json", b"x", content_type="application/json")


async def test_s3_ensure_buckets_creates_only_the_missing_ones() -> None:
    store, stubber = stubbed()
    stubber.add_response("head_bucket", {}, {"Bucket": "bridge-evidence"})
    stubber.add_client_error(
        "head_bucket", service_error_code="404", http_status_code=404, expected_params={"Bucket": "bridge-kyc"}
    )
    stubber.add_client_error(
        "head_bucket",
        service_error_code="NoSuchBucket",
        http_status_code=404,
        expected_params={"Bucket": "bridge-uploads"},
    )
    stubber.add_response("create_bucket", {}, {"Bucket": "bridge-kyc"})
    stubber.add_client_error(  # a second migrate run created it meanwhile: still fine
        "create_bucket",
        service_error_code="BucketAlreadyOwnedByYou",
        http_status_code=409,
        expected_params={"Bucket": "bridge-uploads"},
    )
    with stubber:
        assert await store.ensure_buckets(create=True) == ["kyc-review", "uploads"]
    stubber.assert_no_pending_responses()


async def test_s3_ensure_buckets_without_create_only_checks_and_fails_closed() -> None:
    store, stubber = stubbed()
    stubber.add_response("head_bucket", {}, {"Bucket": "bridge-evidence"})
    stubber.add_client_error(
        "head_bucket", service_error_code="404", http_status_code=404, expected_params={"Bucket": "bridge-kyc"}
    )
    stubber.add_response("head_bucket", {}, {"Bucket": "bridge-uploads"})
    with stubber, pytest.raises(ConfigurationError, match="kyc-review"):
        await store.ensure_buckets(create=False)
    stubber.assert_no_pending_responses()  # and no create_bucket was sent


async def test_s3_ensure_buckets_surfaces_other_errors() -> None:
    store, stubber = stubbed()
    stubber.add_client_error("head_bucket", service_error_code="403", http_status_code=403)
    stubber.add_response("head_bucket", {}, {"Bucket": "bridge-kyc"})
    stubber.add_response("head_bucket", {}, {"Bucket": "bridge-uploads"})
    with stubber, pytest.raises(ClientError):
        await store.ensure_buckets(create=True)
    other, other_stubber = stubbed()
    other_stubber.add_client_error("head_bucket", service_error_code="404", http_status_code=404)
    other_stubber.add_response("head_bucket", {}, {"Bucket": "bridge-kyc"})
    other_stubber.add_response("head_bucket", {}, {"Bucket": "bridge-uploads"})
    other_stubber.add_client_error("create_bucket", service_error_code="BucketAlreadyExists", http_status_code=409)
    with other_stubber, pytest.raises(ClientError):  # the name belongs to someone else
        await other.ensure_buckets(create=True)


def test_the_migrate_step_creates_buckets_in_dev_and_only_checks_elsewhere(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dev_store = InMemoryObjectStore(buckets_exist=False)
    monkeypatch.setattr(storage_cli, "get_settings", lambda: settings(app_env="dev"))
    monkeypatch.setattr(storage_cli, "object_store_from_settings", lambda _settings: dev_store)
    assert storage_cli.main(["ensure-buckets"]) == 0
    assert "created evidence, kyc-review, uploads" in capsys.readouterr().out
    assert storage_cli.main(["ensure-buckets"]) == 0
    assert "every bucket exists" in capsys.readouterr().out

    staging_store = InMemoryObjectStore(buckets_exist=False)
    monkeypatch.setattr(storage_cli, "get_settings", lambda: settings(app_env="staging"))
    monkeypatch.setattr(storage_cli, "object_store_from_settings", lambda _settings: staging_store)
    assert storage_cli.main(["ensure-buckets"]) == 2
    assert "infrastructure" in capsys.readouterr().err
    assert staging_store.buckets == set()


def test_the_migrate_step_waits_for_a_store_that_is_still_starting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Starting(InMemoryObjectStore):
        def __init__(self) -> None:
            super().__init__(buckets_exist=False)
            self.refused = 2

        async def ensure_buckets(self, *, create: bool) -> list[Any]:
            if self.refused:
                self.refused -= 1
                raise EndpointConnectionError(endpoint_url="http://s3:8333")
            return await super().ensure_buckets(create=create)

    starting = Starting()
    naps: list[float] = []
    monkeypatch.setattr(storage_cli, "get_settings", lambda: settings(app_env="dev"))
    monkeypatch.setattr(storage_cli, "object_store_from_settings", lambda _settings: starting)
    monkeypatch.setattr(time, "sleep", naps.append)
    assert storage_cli.main(["ensure-buckets"]) == 0
    assert len(naps) == 2
    never = Starting()
    never.refused = 10**6
    monkeypatch.setattr(storage_cli, "object_store_from_settings", lambda _settings: never)
    assert storage_cli.main(["ensure-buckets", "--wait", "3"]) == 2
    assert "could not reach" in capsys.readouterr().err
