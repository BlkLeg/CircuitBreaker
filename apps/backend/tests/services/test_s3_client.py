"""Tests for services/backup/s3_client.py using moto AWS mock."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from app.services.backup.s3_client import BackupS3Settings, S3Client, S3Error

TEST_SETTINGS = BackupS3Settings(
    bucket="test-cb-backups",
    access_key_id="test-key",
    secret_access_key="test-secret",
    region="us-east-1",
)


@pytest.fixture()
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub AWS creds so moto doesn't complain."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture()
def s3_bucket(aws_credentials: None):  # type: ignore[no-untyped-def]
    """Create a mocked S3 bucket for each test."""
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=TEST_SETTINGS.bucket)
        yield


@pytest.mark.asyncio
async def test_upload_creates_object(tmp_path: pytest.TempPathFactory, s3_bucket: None) -> None:
    """upload() puts the file into the bucket and returns the S3 key."""
    snapshot = tmp_path / "cb-snapshot-20260322-020000.tar.gz"
    snapshot.write_bytes(b"fake-tarball-content")

    client = S3Client(TEST_SETTINGS)
    key = await client.upload(snapshot)

    assert key.endswith("cb-snapshot-20260322-020000.tar.gz")
    assert TEST_SETTINGS.prefix.rstrip("/") in key


@pytest.mark.asyncio
async def test_list_snapshots_returns_sorted(
    tmp_path: pytest.TempPathFactory, s3_bucket: None
) -> None:
    """list_snapshots() returns S3Snapshot objects sorted by last_modified ASC."""
    s3 = boto3.client("s3", region_name="us-east-1")
    for name in ["cb-snapshot-20260320.tar.gz", "cb-snapshot-20260322.tar.gz"]:
        s3.put_object(
            Bucket=TEST_SETTINGS.bucket,
            Key=f"{TEST_SETTINGS.prefix.rstrip('/')}/{name}",
            Body=b"x",
        )

    client = S3Client(TEST_SETTINGS)
    snapshots = await client.list_snapshots()

    assert len(snapshots) == 2
    assert snapshots[0].last_modified <= snapshots[1].last_modified


@pytest.mark.asyncio
async def test_delete_removes_object(tmp_path: pytest.TempPathFactory, s3_bucket: None) -> None:
    """delete() removes the object from S3."""
    s3 = boto3.client("s3", region_name="us-east-1")
    key = f"{TEST_SETTINGS.prefix.rstrip('/')}/cb-snapshot-test.tar.gz"
    s3.put_object(Bucket=TEST_SETTINGS.bucket, Key=key, Body=b"x")

    client = S3Client(TEST_SETTINGS)
    await client.delete(key)

    resp = s3.list_objects_v2(Bucket=TEST_SETTINGS.bucket)
    keys = [o["Key"] for o in resp.get("Contents", [])]
    assert key not in keys


@pytest.mark.asyncio
async def test_probe_succeeds_on_valid_bucket(s3_bucket: None) -> None:
    """probe() completes without raising when the bucket is accessible."""
    client = S3Client(TEST_SETTINGS)
    await client.probe()  # should not raise


@pytest.mark.asyncio
async def test_s3_error_on_missing_bucket(aws_credentials: None) -> None:
    """S3Error raised when the configured bucket does not exist."""
    with mock_aws():
        settings = BackupS3Settings(
            bucket="nonexistent-bucket",
            access_key_id="test-key",
            secret_access_key="test-secret",
        )
        client = S3Client(settings)
        with pytest.raises(S3Error):
            await client.probe()
