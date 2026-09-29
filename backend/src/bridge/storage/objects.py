"""Object storage (ADR-007; D-24): one small async interface over the three buckets.

- ``evidence``: registration manifests (encrypted) and, later, evidence packs. Object Lock (governance) with
  per-object retention is a bucket setting applied by infrastructure (Phase 8 Terraform), not by this code.
- ``kyc-review``: ID images for manual D2 review only (separate, encrypted, no backups, purged 72 h after decision).
- ``uploads``: attachments (presigned uploads arrive with T2.3).

Code names a bucket by its logical name; ``S3_BUCKET_*`` settings map it to the real bucket. Buckets are never
created at first use: ``ensure_buckets`` runs once before the API and worker start (``python -m bridge.storage
ensure-buckets``, the dev compose ``migrate`` step) and creates missing buckets only in dev and test; in staging and
production it only checks them, because infrastructure creates them (Object Lock on ``evidence`` is set at creation).

``InMemoryObjectStore`` serves tests; ``S3ObjectStore`` talks the S3 API through boto3 (AWS S3 in production,
SeaweedFS in dev via ``S3_ENDPOINT_URL``) and is never reached from tests (``tests/egress.py``). Object keys must never
carry personal data or file names (docs/spec/06 6.1): use ids.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Literal, Protocol

from bridge.config import ConfigurationError, Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

BucketName = Literal["evidence", "kyc-review", "uploads"]
BUCKETS: tuple[BucketName, ...] = ("evidence", "kyc-review", "uploads")
_MISSING = frozenset({"NoSuchKey", "404", "NotFound"})
_NO_BUCKET = frozenset({"NoSuchBucket", "404", "NotFound"})


class ObjectNotFoundError(KeyError):
    """No object under that bucket and key."""


class BucketMissingError(RuntimeError):
    """The bucket does not exist (``ensure_buckets`` did not run)."""


def _refuse_missing(missing: list[BucketName]) -> None:
    raise ConfigurationError(
        f"object store buckets missing: {', '.join(missing)} (outside dev and test infrastructure creates them)"
    )


class ObjectStore(Protocol):
    async def put(self, bucket: BucketName, key: str, data: bytes, *, content_type: str) -> None: ...

    async def get(self, bucket: BucketName, key: str) -> bytes: ...

    async def delete(self, bucket: BucketName, key: str) -> None: ...

    async def ensure_buckets(self, *, create: bool) -> list[BucketName]:
        """Every bucket exists afterwards: missing ones are created when ``create`` (dev and test), otherwise
        ``ConfigurationError`` names them. Idempotent; returns the buckets created now."""
        ...


class InMemoryObjectStore:
    """A dict-backed store for tests (``OBJECT_STORE=memory``; refused in staging and production). Its buckets exist
    from the start unless ``buckets_exist=False``; then ``put`` fails until ``ensure_buckets`` creates them."""

    def __init__(self, *, buckets_exist: bool = True) -> None:
        self.objects: dict[tuple[BucketName, str], tuple[bytes, str]] = {}
        self.buckets: set[BucketName] = set(BUCKETS) if buckets_exist else set()

    async def put(self, bucket: BucketName, key: str, data: bytes, *, content_type: str) -> None:
        _check(bucket, key)
        if bucket not in self.buckets:
            raise BucketMissingError(f"bucket {bucket} does not exist")
        self.objects[(bucket, key)] = (bytes(data), content_type)

    async def get(self, bucket: BucketName, key: str) -> bytes:
        try:
            return self.objects[(bucket, key)][0]
        except KeyError:
            raise ObjectNotFoundError(f"{bucket}/{key}") from None

    async def delete(self, bucket: BucketName, key: str) -> None:
        self.objects.pop((bucket, key), None)

    async def ensure_buckets(self, *, create: bool) -> list[BucketName]:
        missing = [name for name in BUCKETS if name not in self.buckets]
        if missing and not create:
            _refuse_missing(missing)
        self.buckets.update(missing)
        return missing


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

    async def ensure_buckets(self, *, create: bool) -> list[BucketName]:
        missing = [name for name in BUCKETS if not await asyncio.to_thread(self._exists, name)]
        if missing and not create:
            _refuse_missing(missing)
        for name in missing:
            await asyncio.to_thread(self._create, name)
        return missing

    def _exists(self, name: BucketName) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket(name))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _NO_BUCKET:
                return False
            raise
        return True

    def _create(self, name: BucketName) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.create_bucket(Bucket=self.bucket(name))
        except ClientError as exc:  # another migrate run created it meanwhile
            if exc.response.get("Error", {}).get("Code") != "BucketAlreadyOwnedByYou":
                raise


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
