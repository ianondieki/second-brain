"""Object storage (ADR-007; D-24): one small async interface over the three buckets.

- ``evidence``: registration manifests (encrypted) and, later, evidence packs. Object Lock (governance) with
  per-object retention is a bucket setting applied by infrastructure (Phase 8 Terraform), not by this code.
- ``kyc-review``: ID images for manual D2 review only (separate, encrypted, no backups, purged 72 h after decision).
- ``uploads``: attachments (presigned uploads arrive with T2.3).

Code names a bucket by its logical name; ``S3_BUCKET_*`` settings map it to the real bucket. ``InMemoryObjectStore``
serves tests; ``S3ObjectStore`` talks the S3 API through boto3 (AWS S3 in production, SeaweedFS in dev via
``S3_ENDPOINT_URL``) and is never reached from tests (``tests/egress.py``). Object keys must never carry personal data
or file names (docs/spec/06 6.1): use ids.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal, Protocol

from bridge.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BucketName = Literal["evidence", "kyc-review", "uploads"]
BUCKETS: tuple[BucketName, ...] = ("evidence", "kyc-review", "uploads")
_MISSING = frozenset({"NoSuchKey", "404", "NotFound"})


class ObjectNotFoundError(KeyError):
    """No object under that bucket and key."""


class ObjectStore(Protocol):
    async def put(self, bucket: BucketName, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, bucket: BucketName, key: str) -> bytes: ...

    async def delete(self, bucket: BucketName, key: str) -> None: ...


class InMemoryObjectStore:
    """A dict-backed store for tests (``OBJECT_STORE=memory``; refused in staging and production)."""

    def __init__(self) -> None:
        self.objects: dict[tuple[BucketName, str], tuple[bytes, str]] = {}

    async def put(self, bucket: BucketName, key: str, data: bytes, *, content_type: str) -> None:
        _check(bucket, key)
        self.objects[(bucket, key)] = (bytes(data), content_type)

    async def get(self, bucket: BucketName, key: str) -> bytes:
        try:
            return self.objects[(bucket, key)][0]
        except KeyError:
            raise ObjectNotFoundError(f"{bucket}/{key}") from None

    async def delete(self, bucket: BucketName, key: str) -> None:
        self.objects.pop((bucket, key), None)


class S3ObjectStore:
    """The S3 API through boto3 (blocking calls run in a worker thread). The client is created on first use."""

    def __init__(
        self,
        buckets: dict[BucketName, str],
        *,
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: S3Client | None = None,
    ) -> None:
        self._buckets = buckets
        self._client_kwargs: dict[str, Any] = {
            "endpoint_url": endpoint_url,
            "region_name": region,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
        }
        self._client = client

    @property
    def client(self) -> S3Client:
        if self._client is None:
            import boto3
            from botocore.config import Config

            # Path-style addressing: SeaweedFS (and most S3 stand-ins) serve buckets under the endpoint's path.
            style: Any = "path" if self._client_kwargs["endpoint_url"] else "auto"
            config = Config(signature_version="s3v4", s3={"addressing_style": style}, retries={"max_attempts": 3})
            self._client = boto3.client("s3", config=config, **self._client_kwargs)
        return self._client

    def bucket(self, name: BucketName) -> str:
        return self._buckets[name]

    async def put(self, bucket: BucketName, key: str, data: bytes, *, content_type: str) -> None:
        _check(bucket, key)
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket(bucket), Key=key, Body=data, ContentType=content_type
        )

    async def get(self, bucket: BucketName, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            response = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket(bucket), Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING:
                raise ObjectNotFoundError(f"{bucket}/{key}") from None
            raise
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, bucket: BucketName, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket(bucket), Key=key)


def _check(bucket: str, key: str) -> None:
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    if not key or key.startswith("/") or ".." in key.split("/"):
        raise ValueError("object keys are relative paths without '..'")


def object_store_from_settings(settings: Settings) -> ObjectStore:
    if settings.object_store == "memory":
        return InMemoryObjectStore()
    secret = settings.s3_secret_access_key
    access = settings.s3_access_key_id
    return S3ObjectStore(
        {
            "evidence": settings.s3_bucket_evidence,
            "kyc-review": settings.s3_bucket_kyc_review,
            "uploads": settings.s3_bucket_uploads,
        },
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=access.get_secret_value() if access else None,
        secret_access_key=secret.get_secret_value() if secret else None,
    )
