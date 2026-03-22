"""Tests for services/backup/snapshot.py.

Uses the real testcontainers Postgres (from conftest.py) and tmp_path for file I/O.
CB_VAULT_KEY is already set to a valid Fernet key in conftest.pytest_configure.
"""

import hashlib
import json
import os
import tarfile
from pathlib import Path

import pytest

from app.db.session import db_url
from app.services.backup.snapshot import BackupError, build_snapshot


@pytest.fixture()
def uploads_dir(tmp_path: Path) -> Path:
    """Fake uploads directory with a couple of files."""
    d = tmp_path / "uploads"
    d.mkdir()
    (d / "icon.png").write_bytes(b"fake-png-data")
    (d / "logo.svg").write_bytes(b"<svg/>")
    return d


@pytest.mark.asyncio
async def test_build_snapshot_creates_tarball(
    setup_db: None, tmp_path: Path, uploads_dir: Path
) -> None:
    """build_snapshot returns a .tar.gz that exists and has mode 0600."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    path = await build_snapshot(
        backup_dir=backup_dir,
        db_url=db_url,
        vault_key=os.environ["CB_VAULT_KEY"],
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    assert path.exists()
    assert path.name.startswith("cb-snapshot-")
    assert path.name.endswith(".tar.gz")
    # Must be 0600
    assert oct(path.stat().st_mode & 0o777) == oct(0o600)


@pytest.mark.asyncio
async def test_build_snapshot_tarball_contents(
    setup_db: None, tmp_path: Path, uploads_dir: Path
) -> None:
    """Tarball contains db.sql.gz, vault.key, uploads/, manifest.json."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    path = await build_snapshot(
        backup_dir=backup_dir,
        db_url=db_url,
        vault_key=os.environ["CB_VAULT_KEY"],
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    with tarfile.open(path, "r:gz") as tf:
        names = tf.getnames()

    # Check required files are present (paths include the top-level dir)
    assert any("db.sql.gz" in n for n in names)
    assert any("vault.key" in n for n in names)
    assert any("manifest.json" in n for n in names)
    assert any("uploads/icon.png" in n for n in names)


@pytest.mark.asyncio
async def test_build_snapshot_vault_key_stored(
    setup_db: None, tmp_path: Path, uploads_dir: Path
) -> None:
    """vault.key inside tarball matches the CB_VAULT_KEY env var."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    expected_key = os.environ["CB_VAULT_KEY"]

    path = await build_snapshot(
        backup_dir=backup_dir,
        db_url=db_url,
        vault_key=expected_key,
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    with tarfile.open(path, "r:gz") as tf:
        vault_member = next(m for m in tf.getmembers() if "vault.key" in m.name)
        content = tf.extractfile(vault_member)
        assert content is not None
        assert content.read().decode().strip() == expected_key


@pytest.mark.asyncio
async def test_build_snapshot_manifest_checksum(
    setup_db: None, tmp_path: Path, uploads_dir: Path
) -> None:
    """manifest.json db_checksum_sha256 matches actual db.sql.gz content."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    path = await build_snapshot(
        backup_dir=backup_dir,
        db_url=db_url,
        vault_key=os.environ["CB_VAULT_KEY"],
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    with tarfile.open(path, "r:gz") as tf:
        manifest_m = next(m for m in tf.getmembers() if "manifest.json" in m.name)
        db_m = next(m for m in tf.getmembers() if "db.sql.gz" in m.name)

        manifest = json.loads(tf.extractfile(manifest_m).read())  # type: ignore[union-attr]
        db_bytes = tf.extractfile(db_m).read()  # type: ignore[union-attr]

    actual_sha = hashlib.sha256(db_bytes).hexdigest()
    assert manifest["db_checksum_sha256"] == actual_sha
    assert manifest["cb_version"] == "0.1.2"
    assert "created_at" in manifest
    assert manifest["uploads_count"] == 2


@pytest.mark.asyncio
async def test_build_snapshot_raises_on_pg_dump_failure(
    setup_db: None, tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BackupError is raised when pg_dump fails; no partial file left behind."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Make pg_dump fail by patching subprocess.run to raise
    import subprocess

    original_run = subprocess.run

    def bad_run(cmd: list, **kwargs):  # type: ignore[no-untyped-def]
        if "pg_dump" in cmd[0]:
            raise subprocess.CalledProcessError(1, cmd, stderr=b"intentional failure")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", bad_run)

    with pytest.raises(BackupError, match="pg_dump"):
        await build_snapshot(
            backup_dir=backup_dir,
            db_url=db_url,
            vault_key=os.environ["CB_VAULT_KEY"],
            uploads_dir=uploads_dir,
            cb_version="0.1.2",
        )

    # No partial tarball left
    assert list(backup_dir.glob("cb-snapshot-*.tar.gz")) == []
