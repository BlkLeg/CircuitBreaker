"""Tests for services/backup/pruner.py."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.backup.pruner import prune_local, prune_remote
from app.services.backup.s3_client import S3Client, S3Snapshot


def _make_snapshots(tmp_path: Path, count: int) -> list[Path]:
    """Create `count` fake tarball files with staggered mtimes."""
    files = []
    for i in range(count):
        f = tmp_path / f"cb-snapshot-2026032{i}-020000.tar.gz"
        f.write_bytes(b"x")
        # Set mtime so ordering is deterministic: older files have lower mtime
        os.utime(f, (time.time() - (count - i) * 3600, time.time() - (count - i) * 3600))
        files.append(f)
    return files


def test_prune_local_keeps_newest(tmp_path: Path) -> None:
    """prune_local deletes oldest files beyond the keep count."""
    _make_snapshots(tmp_path, 5)
    deleted = prune_local(tmp_path, keep=3)

    assert len(deleted) == 2
    # The two oldest should be deleted
    for f in deleted:
        assert not f.exists()
    # The three newest should remain
    remaining = sorted(tmp_path.glob("cb-snapshot-*.tar.gz"))
    assert len(remaining) == 3


def test_prune_local_noop_when_keep_zero(tmp_path: Path) -> None:
    """prune_local is a no-op when keep <= 0."""
    _make_snapshots(tmp_path, 3)
    deleted = prune_local(tmp_path, keep=0)
    assert deleted == []
    assert len(list(tmp_path.glob("cb-snapshot-*.tar.gz"))) == 3


def test_prune_local_noop_when_under_limit(tmp_path: Path) -> None:
    """prune_local does nothing when file count <= keep."""
    _make_snapshots(tmp_path, 2)
    deleted = prune_local(tmp_path, keep=5)
    assert deleted == []


@pytest.mark.asyncio
async def test_prune_remote_deletes_oldest(tmp_path: Path) -> None:
    """prune_remote deletes oldest S3 snapshots beyond keep count."""
    snapshots = [
        S3Snapshot(
            key="prefix/cb-snapshot-20260320.tar.gz",
            size_bytes=100,
            last_modified=datetime(2026, 3, 20, tzinfo=UTC),
        ),
        S3Snapshot(
            key="prefix/cb-snapshot-20260321.tar.gz",
            size_bytes=100,
            last_modified=datetime(2026, 3, 21, tzinfo=UTC),
        ),
        S3Snapshot(
            key="prefix/cb-snapshot-20260322.tar.gz",
            size_bytes=100,
            last_modified=datetime(2026, 3, 22, tzinfo=UTC),
        ),
    ]

    mock_client = MagicMock(spec=S3Client)
    mock_client.list_snapshots = AsyncMock(return_value=snapshots)
    mock_client.delete = AsyncMock()

    deleted = await prune_remote(mock_client, keep=2)

    assert deleted == ["prefix/cb-snapshot-20260320.tar.gz"]
    mock_client.delete.assert_called_once_with("prefix/cb-snapshot-20260320.tar.gz")


@pytest.mark.asyncio
async def test_prune_remote_noop_when_keep_zero(tmp_path: Path) -> None:
    """prune_remote is a no-op when keep <= 0."""
    mock_client = MagicMock(spec=S3Client)
    mock_client.list_snapshots = AsyncMock(return_value=[])
    mock_client.delete = AsyncMock()

    deleted = await prune_remote(mock_client, keep=0)

    assert deleted == []
    mock_client.list_snapshots.assert_not_called()
