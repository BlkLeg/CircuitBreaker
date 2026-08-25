"""Tests for services/backup/snapshot.py.

Uses the real testcontainers Postgres (from conftest.py) and tmp_path for file I/O.
CB_VAULT_KEY is already set to a valid Fernet key in conftest.pytest_configure.
"""

import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

from app.db.session import db_url
from app.services.backup.snapshot import BackupError, build_snapshot

# `build_snapshot` shells out to the real `pg_dump` binary (it dumps the
# testcontainers Postgres over the wire). The binary ships in the
# postgresql-client OS package, which is NOT a Python dependency and is not
# installed by `poetry install` — so on a workstation without it these tests
# fail with BackupError("[Errno 2] ... 'pg_dump'"), which says nothing about
# the code under test. Skip rather than xfail: this is a missing tool, not a
# known-broken behaviour, and an xfail would silently swallow a genuine
# regression on machines that *do* have pg_dump.
#
# Note this only covers the tests that invoke pg_dump for real.
# `test_build_snapshot_raises_on_pg_dump_failure` monkeypatches
# `subprocess.run` and therefore still runs everywhere.
requires_pg_dump = pytest.mark.skipif(
    shutil.which("pg_dump") is None,
    reason="pg_dump binary not installed (postgresql-client); required to build a real snapshot",
)


@pytest.fixture()
def uploads_dir(tmp_path: Path) -> Path:
    """Fake uploads directory with a couple of files."""
    d = tmp_path / "uploads"
    d.mkdir()
    (d / "icon.png").write_bytes(b"fake-png-data")
    (d / "logo.svg").write_bytes(b"<svg/>")
    return d


@requires_pg_dump
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


@requires_pg_dump
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


@requires_pg_dump
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


@requires_pg_dump
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


def _fake_pg_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the pg_dump binary.

    The manifest fields under test are independent of the dump's contents, so these
    tests run everywhere instead of skipping on hosts without postgresql-client.
    """
    import subprocess

    original_run = subprocess.run

    def fake_run(cmd: list, **kwargs):  # type: ignore[no-untyped-def]
        if cmd and "pg_dump" in cmd[0]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"-- fake dump\n", stderr=b"")
        return original_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


async def _build(tmp_path: Path, uploads_dir: Path) -> Path:
    """Build a snapshot into tmp_path/backups and return the tarball path."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(exist_ok=True)
    return await build_snapshot(
        backup_dir=backup_dir,
        db_url=db_url,
        vault_key=os.environ["CB_VAULT_KEY"],
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )


def _read_manifest(tarball: Path) -> dict:
    """Read manifest.json out of a snapshot tarball."""
    with tarfile.open(tarball, "r:gz") as tf:
        member = next(m for m in tf.getmembers() if "manifest.json" in m.name)
        payload = tf.extractfile(member)
        assert payload is not None
        return json.loads(payload.read())


@pytest.mark.asyncio
async def test_manifest_declares_a_format_version(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restore that half-understands an archive is the failure this batch exists to end."""
    _fake_pg_dump(monkeypatch)

    tarball = await _build(tmp_path, uploads_dir)
    manifest = _read_manifest(tarball)

    assert manifest["format_version"] == 1


@pytest.mark.asyncio
async def test_manifest_records_the_install_mode(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pg_dump(monkeypatch)
    monkeypatch.setenv("CB_INSTALL_MODE", "compose")

    tarball = await _build(tmp_path, uploads_dir)
    manifest = _read_manifest(tarball)

    assert manifest["install_mode"] == "compose"


@pytest.mark.asyncio
async def test_manifest_install_mode_is_unknown_when_unset(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pg_dump(monkeypatch)
    monkeypatch.delenv("CB_INSTALL_MODE", raising=False)

    tarball = await _build(tmp_path, uploads_dir)
    manifest = _read_manifest(tarball)

    assert manifest["install_mode"] == "unknown"


def test_cb_backup_invokes_the_snapshot_cli_and_nothing_else() -> None:
    """INC-15: `cb backup` built its own archive — database.sql, manifest.txt, no vault key —
    which `deploy/scripts/restore.sh` structurally rejected. There must be one builder."""
    cb_src = (Path(__file__).resolve().parents[4] / "cb").read_text(encoding="utf-8")
    start = cb_src.index("cmd_backup()")
    body = cb_src[start : cb_src.index("\ncmd_", start + 1)]

    assert "app.cli snapshot create" in body, (
        "cb backup no longer reaches the snapshot CLI — a second backup implementation is "
        "how the two formats diverged."
    )
    for legacy in ("pg_dump", "database.sql", "manifest.txt"):
        assert legacy not in body, f"cb backup still builds its own archive ({legacy})"


def test_snapshot_captures_the_reverse_proxy_the_installer_configures() -> None:
    """The installer configures nginx (deploy/setup.sh:841). Capturing /etc/caddy meant the
    config/ section was silently empty on every real install."""
    import inspect

    from app.services.backup import snapshot

    source = inspect.getsource(snapshot)
    assert "/etc/nginx/conf.d/circuitbreaker.conf" in source, (
        "the snapshot does not capture the nginx config the installer writes"
    )
    assert "/etc/caddy" not in source, "the snapshot still captures Caddy paths that never exist"
