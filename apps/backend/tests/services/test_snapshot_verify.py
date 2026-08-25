"""Archive verification — the checks that must run before anything is destroyed.

INC-15: `cb backup` produced an archive `deploy/scripts/restore.sh` structurally rejects,
and there was no restore for two of the three install modes. These tests cover the refusal
paths, which are the ones an operator meets when a restore is already going wrong.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
from pathlib import Path

import pytest

from app.services.backup.verify import SnapshotProblem, verify_archive


def _make_archive(
    tmp_path: Path,
    *,
    manifest: dict | None = None,
    db_bytes: bytes = b"-- dump\n",
    vault: str = "a-vault-key",
    omit: set[str] | None = None,
) -> Path:
    omit = omit or set()
    inner = tmp_path / "cb-snapshot-test"
    inner.mkdir(parents=True, exist_ok=True)

    gz = gzip.compress(db_bytes)
    checksum = hashlib.sha256(gz).hexdigest()
    if "db.sql.gz" not in omit:
        (inner / "db.sql.gz").write_bytes(gz)
    if "vault.key" not in omit:
        (inner / "vault.key").write_text(vault, encoding="utf-8")
    if "manifest.json" not in omit:
        body = (
            manifest
            if manifest is not None
            else {
                "format_version": 1,
                "install_mode": "docker",
                "cb_version": "1.0.0",
                "created_at": "2026-08-24T00:00:00+00:00",
                "db_name": "circuitbreaker",
                "uploads_count": 0,
                "db_checksum_sha256": checksum,
                "config_files": [],
            }
        )
        (inner / "manifest.json").write_text(json.dumps(body), encoding="utf-8")

    dest = tmp_path / "snap.tar.gz"
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(inner, arcname=inner.name)
    return dest


def test_accepts_a_well_formed_archive(tmp_path):
    manifest = verify_archive(_make_archive(tmp_path), installed_version="1.0.0")

    assert manifest["db_name"] == "circuitbreaker"


@pytest.mark.parametrize("member", ["db.sql.gz", "vault.key", "manifest.json"])
def test_rejects_a_missing_member(tmp_path, member):
    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(_make_archive(tmp_path, omit={member}))

    assert member in str(excinfo.value)


def test_rejects_a_checksum_mismatch(tmp_path):
    archive = _make_archive(
        tmp_path,
        manifest={
            "format_version": 1,
            "install_mode": "docker",
            "cb_version": "1.0.0",
            "created_at": "2026-08-24T00:00:00+00:00",
            "db_name": "circuitbreaker",
            "uploads_count": 0,
            "db_checksum_sha256": "0" * 64,
            "config_files": [],
        },
    )

    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(archive)

    assert "checksum" in str(excinfo.value).lower()


def test_rejects_an_empty_vault_key(tmp_path):
    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(_make_archive(tmp_path, vault=""))

    assert "vault" in str(excinfo.value).lower()


def test_rejects_a_newer_cb_version(tmp_path):
    archive = _make_archive(
        tmp_path,
        manifest={
            "format_version": 1,
            "install_mode": "docker",
            "cb_version": "2.0.0",
            "created_at": "2026-08-24T00:00:00+00:00",
            "db_name": "circuitbreaker",
            "uploads_count": 0,
            "db_checksum_sha256": hashlib.sha256(gzip.compress(b"-- dump\n")).hexdigest(),
            "config_files": [],
        },
    )

    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(archive, installed_version="1.0.0")

    assert "newer" in str(excinfo.value).lower()


def test_accepts_a_manifest_with_no_format_version(tmp_path):
    """Archives predating Task 1 must still restore — they read as version 0."""
    archive = _make_archive(
        tmp_path,
        manifest={
            "cb_version": "1.0.0",
            "created_at": "2026-08-24T00:00:00+00:00",
            "db_name": "circuitbreaker",
            "uploads_count": 0,
            "db_checksum_sha256": hashlib.sha256(gzip.compress(b"-- dump\n")).hexdigest(),
            "config_files": [],
        },
    )

    manifest = verify_archive(archive, installed_version="1.0.0")

    assert manifest.get("format_version", 0) == 0


def test_names_an_old_cb_backup_archive_specifically(tmp_path):
    """`cb backup` produced database.sql + manifest.txt. Say so, rather than failing on a
    missing db.sql.gz — an operator holding one needs to know it never was restorable."""
    inner = tmp_path / "cb-backup-test"
    inner.mkdir()
    (inner / "database.sql").write_text("-- dump\n", encoding="utf-8")
    (inner / "manifest.txt").write_text("mode=docker\n", encoding="utf-8")
    dest = tmp_path / "old.tar.gz"
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(inner, arcname=inner.name)

    with pytest.raises(SnapshotProblem) as excinfo:
        verify_archive(dest)

    assert "cb backup" in str(excinfo.value)
