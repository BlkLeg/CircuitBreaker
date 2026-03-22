"""S3-compatible backup client.

Supports AWS S3, MinIO, Cloudflare R2 — any S3-compatible endpoint.
Uses boto3 via asyncio.to_thread so the async interface is non-blocking
without requiring aiobotocore (which has moto compatibility issues).
All public methods raise S3Error on failure.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import boto3
import boto3.exceptions
from botocore.exceptions import BotoCoreError, ClientError

_logger = logging.getLogger(__name__)


class S3Error(RuntimeError):
    """Raised when an S3 operation fails."""


@dataclass(frozen=True)
class BackupS3Settings:
    """Decrypted S3 credentials and configuration."""

    bucket: str
    access_key_id: str
    secret_access_key: str
    region: str = "us-east-1"
    endpoint_url: str | None = None
    prefix: str = "circuitbreaker/backups/"


@dataclass
class S3Snapshot:
    """Metadata for a single snapshot object in S3."""

    key: str
    size_bytes: int
    last_modified: datetime


class S3Client:
    """Async S3 client for Circuit Breaker backup operations.

    Uses boto3 (sync) dispatched via asyncio.to_thread so the caller
    gets a non-blocking async interface without aiobotocore complexity.
    """

    def __init__(self, settings: BackupS3Settings) -> None:
        self._settings = settings
        kwargs: dict[str, Any] = {
            "service_name": "s3",
            "aws_access_key_id": settings.access_key_id,
            "aws_secret_access_key": settings.secret_access_key,
            "region_name": settings.region,
        }
        if settings.endpoint_url:
            kwargs["endpoint_url"] = settings.endpoint_url
        self._s3 = boto3.client(**kwargs)

    def _upload_file_sync(self, path: Path, key: str) -> None:
        self._s3.upload_file(str(path), self._settings.bucket, key)

    def _list_objects_sync(self, prefix: str) -> list[S3Snapshot]:
        results: list[S3Snapshot] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._settings.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                results.append(
                    S3Snapshot(
                        key=obj["Key"],
                        size_bytes=obj["Size"],
                        last_modified=obj["LastModified"],
                    )
                )
        return results

    def _delete_object_sync(self, key: str) -> None:
        self._s3.delete_object(Bucket=self._settings.bucket, Key=key)

    def _generate_presigned_url_sync(self, key: str, expires: int) -> str:
        return self._s3.generate_presigned_url(  # type: ignore[no-any-return]
            "get_object",
            Params={"Bucket": self._settings.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def _probe_sync(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".probe", delete=True) as tmp:
            tmp.write(b"\x00")
            tmp.flush()
            self._s3.upload_file(
                tmp.name, self._settings.bucket, f"{self._settings.prefix.rstrip('/')}/.cb-probe"
            )

    async def upload(self, path: Path) -> str:
        """Upload a file to S3. Returns the S3 key.

        Uses the S3 transfer manager which handles multipart automatically.
        """
        key = f"{self._settings.prefix.rstrip('/')}/{path.name}"
        try:
            await asyncio.to_thread(self._upload_file_sync, path, key)
            _logger.info("Uploaded snapshot to S3: %s", key)
            return key
        except (BotoCoreError, ClientError, boto3.exceptions.S3UploadFailedError) as exc:
            raise S3Error(f"S3 upload failed: {exc}") from exc

    async def list_snapshots(self) -> list[S3Snapshot]:
        """List snapshot objects sorted by last_modified ascending."""
        prefix = self._settings.prefix.rstrip("/") + "/"
        try:
            results = await asyncio.to_thread(self._list_objects_sync, prefix)
        except (BotoCoreError, ClientError) as exc:
            raise S3Error(f"S3 list failed: {exc}") from exc
        results.sort(key=lambda s: s.last_modified)
        return results

    async def delete(self, key: str) -> None:
        """Delete a single object from S3."""
        try:
            await asyncio.to_thread(self._delete_object_sync, key)
            _logger.info("Deleted S3 object: %s", key)
        except (BotoCoreError, ClientError) as exc:
            raise S3Error(f"S3 delete failed: {exc}") from exc

    async def generate_presigned_url(self, key: str, expires: int = 3600) -> str:
        """Generate a presigned GET URL for a snapshot object."""
        try:
            return await asyncio.to_thread(self._generate_presigned_url_sync, key, expires)
        except (BotoCoreError, ClientError) as exc:
            raise S3Error(f"S3 presign failed: {exc}") from exc

    async def probe(self) -> None:
        """Upload a 1-byte probe object to verify bucket access.

        Raises S3Error if the bucket is unreachable or credentials are invalid.
        """
        try:
            await asyncio.to_thread(self._probe_sync)
            _logger.debug("S3 probe succeeded for bucket %s", self._settings.bucket)
        except (BotoCoreError, ClientError, boto3.exceptions.S3UploadFailedError) as exc:
            raise S3Error(f"S3 probe failed: {exc}") from exc
