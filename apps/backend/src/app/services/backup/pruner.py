"""Snapshot retention pruner.

Manages local disk and S3 snapshot retention by count.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.services.backup.s3_client import S3Client

_logger = logging.getLogger(__name__)


def prune_local(backup_dir: Path, keep: int) -> list[Path]:
    """Delete oldest local snapshots beyond `keep` count.

    Sorts cb-snapshot-*.tar.gz files by mtime ascending, deletes all
    beyond the newest `keep` files.

    Args:
        backup_dir: Directory containing snapshot tarballs.
        keep: Number of newest snapshots to retain. No-op when <= 0.

    Returns:
        List of deleted file paths.
    """
    if keep <= 0:
        return []

    snapshots = sorted(
        backup_dir.glob("cb-snapshot-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
    )

    to_delete = snapshots[: max(0, len(snapshots) - keep)]
    deleted: list[Path] = []
    for path in to_delete:
        try:
            path.unlink()
            deleted.append(path)
            _logger.info("Pruned local snapshot: %s", path.name)
        except OSError as exc:
            _logger.warning("Failed to prune local snapshot %s: %s", path.name, exc)

    return deleted


async def prune_remote(client: S3Client, keep: int) -> list[str]:
    """Delete oldest S3 snapshots beyond `keep` count.

    Calls client.list_snapshots() (sorted ASC by last_modified) and
    deletes all beyond the newest `keep` objects.

    Args:
        client: S3Client instance.
        keep: Number of newest snapshots to retain. No-op when <= 0.

    Returns:
        List of deleted S3 keys.
    """
    if keep <= 0:
        return []

    snapshots = await client.list_snapshots()
    to_delete = snapshots[: max(0, len(snapshots) - keep)]
    deleted: list[str] = []
    for snap in to_delete:
        try:
            await client.delete(snap.key)
            deleted.append(snap.key)
            _logger.info("Pruned remote snapshot: %s", snap.key)
        except Exception as exc:
            _logger.warning("Failed to prune remote snapshot %s: %s", snap.key, exc)

    return deleted
