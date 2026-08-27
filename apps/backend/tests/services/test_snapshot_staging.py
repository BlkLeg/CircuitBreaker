"""Regression tests for snapshot staging location and pg_dump streaming (B11, B12).

Two shipped defects, both in ``services/backup/snapshot.py`` and both invisible on a
developer workstation, where /tmp is a large disk-backed directory and the demo database
is a few megabytes:

  B11  ``subprocess.run(..., capture_output=True)`` buffered the ENTIRE pg_dump into a
       Python bytes object before a single byte was compressed. A 1 GB database is a
       1 GB resident allocation inside a container capped at 2 GB, and the daily
       snapshot job takes the whole application down with it.

  B12  ``tempfile.mkdtemp()`` with no ``dir=`` stages under the system temp dir. In the
       shipped Docker deployment /tmp is ``tmpfs size=100M`` (docker-compose.yml) on a
       ``read_only: true`` root filesystem, so the staging tree — the dump plus an
       uncompressed copy of uploads/ — runs out of space long before the tarball exists.

Neither test needs Postgres. They put a fake ``pg_dump`` on PATH, which is how the real
binary is resolved (``_pg_env_from_url`` copies os.environ, PATH included), so the code
under test runs unmodified: a real fork/exec, a real pipe, real streaming.
"""

import gzip
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import time
import tracemalloc
from pathlib import Path

import pytest

from app.services.backup.snapshot import BackupError, build_snapshot

# How much the fake pg_dump emits, and the ceiling the streaming implementation must
# stay under. The gap has to be wide enough that ordinary interpreter churn during the
# build cannot close it, and narrow enough that buffering the dump whole cannot hide
# under it: 64 MiB dumped against a 16 MiB ceiling is a 4x margin in both directions.
_DUMP_BYTES = 64 * 1024 * 1024
_PEAK_CEILING_BYTES = 16 * 1024 * 1024


def _install_fake_pg_dump(
    monkeypatch: pytest.MonkeyPatch,
    bin_dir: Path,
    *,
    payload_bytes: int = 4096,
    exit_code: int = 0,
    stderr_text: str = "",
    source: str = "/dev/urandom",
) -> None:
    """Put a fake ``pg_dump`` first on PATH.

    ``source`` defaults to /dev/urandom, not /dev/zero, and that is load-bearing for the
    memory test. B11 has two halves — buffering the dump on the way in, and reading the
    finished db.sql.gz whole to checksum it — and a dump of zeros gzips ~1000:1, so the
    second half is invisible to tracemalloc when the payload compresses. Incompressible
    bytes make the archive as big as the dump, so a whole-file read of either end blows
    the ceiling. Do not "optimise" this back to /dev/zero.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "pg_dump"
    script.write_text(
        "#!/bin/sh\n"
        f'[ -n "{stderr_text}" ] && printf %s "{stderr_text}" >&2\n'
        f"head -c {payload_bytes} {source}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def _same_dir(actual: str, expected: Path) -> bool:
    """Path comparison, kept in a sync helper so ASYNC240 does not flag resolve()."""
    return Path(actual).resolve() == expected.resolve()


@pytest.fixture()
def uploads_dir(tmp_path: Path) -> Path:
    d = tmp_path / "uploads"
    d.mkdir()
    (d / "icon.png").write_bytes(b"fake-png-data")
    return d


async def test_pg_dump_is_streamed_not_buffered_whole(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B11: peak Python heap during the build must not scale with the dump size.

    tracemalloc sees the bytes object ``subprocess.run(capture_output=True)`` builds,
    because large allocations pass through the traced raw allocator. Streaming the pipe
    into gzip in fixed blocks keeps the peak at block size; buffering the dump whole puts
    the entire database on the heap at once, which is the OOM.

    Both halves of B11 are in scope here — the buffered dump AND the
    ``db_gz_path.read_bytes()`` that used to checksum the finished archive in one
    allocation. The fake dump emits incompressible bytes precisely so the second one
    shows up: with a compressible payload the archive is a few KB and a whole-file read
    of it never touches the ceiling, which is how that half of the fix once shipped
    with no test behind it.
    """
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin", payload_bytes=_DUMP_BYTES)
    backup_dir = tmp_path / "backups"

    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        tarball = await build_snapshot(
            backup_dir=backup_dir,
            db_url="postgresql://u:p@localhost:5432/cb",
            vault_key="test-vault-key",
            uploads_dir=uploads_dir,
            cb_version="0.1.2",
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert tarball.exists()
    assert peak < _PEAK_CEILING_BYTES, (
        f"peak heap was {peak / 1024 / 1024:.1f} MiB while dumping "
        f"{_DUMP_BYTES / 1024 / 1024:.0f} MiB — pg_dump output is being buffered in "
        "memory instead of streamed, which OOMs the 2 GB mono container on a real database"
    )


async def test_streamed_dump_survives_the_tarball_intact(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B11 corollary: streaming must not truncate the dump or change what is checksummed.

    Two ways the rewrite could have produced a backup nothing can restore. A block loop
    that drops the tail is silently unrestorable, which is worse than the OOM it
    replaced. And the streamed checksum has to keep covering the COMPRESSED db.sql.gz
    bytes: ``verify.py`` hashes exactly those when it validates an archive, so a digest
    taken over the raw SQL instead would fail every snapshot ever taken — including the
    one an operator is trying to restore from — while every isolated unit test still
    passed. The manifest digest is therefore compared against the archived bytes here,
    not merely asserted to exist.
    """
    payload = 3 * 1024 * 1024 + 7  # deliberately not a whole number of 1 MiB blocks
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin", payload_bytes=payload)
    backup_dir = tmp_path / "backups"

    tarball = await build_snapshot(
        backup_dir=backup_dir,
        db_url="postgresql://u:p@localhost:5432/cb",
        vault_key="test-vault-key",
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    with tarfile.open(tarball, "r:gz") as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith("db.sql.gz"))
        stream = tf.extractfile(member)
        assert stream is not None
        archived = stream.read()
        manifest_member = next(m for m in tf.getmembers() if m.name.endswith("manifest.json"))
        manifest_stream = tf.extractfile(manifest_member)
        assert manifest_stream is not None
        manifest = json.loads(manifest_stream.read())

    assert len(gzip.decompress(archived)) == payload
    assert manifest["db_checksum_sha256"] == hashlib.sha256(archived).hexdigest(), (
        "the manifest digest does not cover the compressed db.sql.gz bytes — "
        "verify.py hashes exactly those, so this archive will fail verification"
    )


async def test_staging_never_uses_the_system_temp_dir(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B12: the build must succeed with the system temp dir unusable.

    Standing in for the shipped container's 100 MB tmpfs with a temp dir that does not
    exist at all: any code path that still stages there fails outright, whatever uid the
    test runs as. The real deployment fails the same way, just later and with ENOSPC.
    """
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "no-such-tmpfs"))
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin")

    tarball = await build_snapshot(
        backup_dir=tmp_path / "backups",
        db_url="postgresql://u:p@localhost:5432/cb",
        vault_key="test-vault-key",
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    assert tarball.exists()
    assert (tmp_path / "data" / "tmp").is_dir(), (
        "the staging root under CB_DATA_DIR was never created — staging is not on the "
        "persistent data volume"
    )


async def test_staging_directory_lives_under_the_data_volume(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B12, named directly: mkdtemp must be given a dir= on the data volume.

    The staging tree is deleted in the ``finally``, so the only way to observe where it
    was is to watch the call that creates it.
    """
    seen: list[str | None] = []
    real_mkdtemp = tempfile.mkdtemp

    def spy(*args: object, **kwargs: object) -> str:
        seen.append(kwargs.get("dir"))  # type: ignore[arg-type]
        return real_mkdtemp(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin")

    await build_snapshot(
        backup_dir=tmp_path / "backups",
        db_url="postgresql://u:p@localhost:5432/cb",
        vault_key="test-vault-key",
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    assert seen, "snapshot staging no longer goes through tempfile.mkdtemp"
    assert seen[0] is not None, "mkdtemp was called without dir= — staging lands on /tmp"
    assert _same_dir(seen[0], tmp_path / "data" / "tmp")


async def test_pg_dump_failure_still_raises_backup_error(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-zero pg_dump must still raise BackupError — and stderr must be a FILE.

    stderr has to reach the message: an operator staring at "snapshot failed" with no
    reason is how a broken backup goes unnoticed for a month. The kwargs assertion is
    the other half. ``capture_output=True`` reaches Popen as ``stderr=PIPE``, so
    restoring B11's buffered form fails here as well as in the memory test. And the
    obvious "just add stderr=PIPE" rewrite deadlocks: draining stdout to EOF while
    stderr sits in an undrained 64 KB pipe blocks pg_dump forever the first time it is
    chatty, which no assertion about the error message would ever catch.
    """
    seen: list[dict[str, object]] = []
    real_popen = subprocess.Popen

    def spy(*args: object, **kwargs: object) -> subprocess.Popen:  # type: ignore[type-arg]
        seen.append(dict(kwargs))
        return real_popen(*args, **kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(subprocess, "Popen", spy)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    _install_fake_pg_dump(
        monkeypatch,
        tmp_path / "bin",
        payload_bytes=0,
        exit_code=1,
        stderr_text="FATAL: database does not exist",
    )
    backup_dir = tmp_path / "backups"

    with pytest.raises(BackupError, match="database does not exist"):
        await build_snapshot(
            backup_dir=backup_dir,
            db_url="postgresql://u:p@localhost:5432/cb",
            vault_key="test-vault-key",
            uploads_dir=uploads_dir,
            cb_version="0.1.2",
        )

    assert list(backup_dir.glob("cb-snapshot-*.tar.gz")) == []
    assert seen, "the snapshot builder no longer launches pg_dump through subprocess.Popen"
    kwargs = seen[0]
    assert kwargs.get("stdout") is subprocess.PIPE, (
        "pg_dump stdout is not a pipe — the dump is not being streamed"
    )
    stderr = kwargs.get("stderr")
    assert stderr is not subprocess.PIPE, (
        "pg_dump stderr is a PIPE. Either capture_output=True is back (B11: the whole "
        "dump lands on the heap), or stderr was piped without a reader (deadlock)."
    )
    assert hasattr(stderr, "fileno"), f"pg_dump stderr must be a real file, got {stderr!r}"


async def test_orphaned_staging_dirs_are_swept(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B12's own cost: staging now lives somewhere nothing ever wipes.

    On the old /tmp tmpfs an interrupted snapshot cleaned up for free — Docker emptied
    the mount on every restart. On the data volume nothing does, and the ``finally``
    that removes the staging tree does not run on SIGKILL, which is exactly how an
    OOM-killed snapshot ends. Each orphan is an uncompressed copy of uploads/ plus the
    dump, sitting on the same volume as pgdata, so an unswept staging root fills the
    disk Postgres runs on — strictly worse than the 100 MB tmpfs ENOSPC being fixed.
    """
    staging_root = tmp_path / "data" / "tmp"
    staging_root.mkdir(parents=True)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))

    orphan = staging_root / "cb-snapshot-abandoned"
    (orphan / "cb-snapshot-20200101-000000" / "uploads").mkdir(parents=True)
    (orphan / "cb-snapshot-20200101-000000" / "db.sql.gz").write_bytes(b"x" * 4096)
    old = time.time() - 7 * 3600
    os.utime(orphan, (old, old))

    live = staging_root / "cb-snapshot-inflight"
    live.mkdir()

    unrelated = staging_root / "certbot-workdir"
    unrelated.mkdir()
    os.utime(unrelated, (old, old))

    # A finished tarball shares the cb-snapshot-* prefix. Nothing stops an operator from
    # pointing BACKUP_DIR at the staging root, and a sweep that deleted archives would
    # turn a disk-hygiene chore into data loss.
    archive = staging_root / "cb-snapshot-20200101-000000.tar.gz"
    archive.write_bytes(b"not a staging dir")
    os.utime(archive, (old, old))

    _install_fake_pg_dump(monkeypatch, tmp_path / "bin")
    await build_snapshot(
        backup_dir=tmp_path / "backups",
        db_url="postgresql://u:p@localhost:5432/cb",
        vault_key="test-vault-key",
        uploads_dir=uploads_dir,
        cb_version="0.1.2",
    )

    assert not orphan.exists(), (
        "an abandoned staging tree from a killed snapshot survived the next run — "
        "orphans now accumulate forever on the volume that also holds pgdata"
    )
    assert live.is_dir(), "the sweep deleted a staging dir young enough to be a live build"
    assert unrelated.is_dir(), "the sweep reached outside its own cb-snapshot-* namespace"
    assert archive.is_file(), "the sweep deleted a finished snapshot archive, not a staging dir"


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores directory permissions, so nothing is unwritable"
)
async def test_unwritable_staging_root_fails_as_backup_error(
    tmp_path: Path, uploads_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging root that exists but cannot be written to must not escape as a 500.

    docker/entrypoint-mono.sh warns and carries on when its ``chown -R`` on the data
    volume is not permitted, leaving ${CB_DATA_DIR}/tmp present and unwritable.
    ``mkdir(exist_ok=True)`` does not raise on that, so the failure surfaces from
    ``mkdtemp`` — and unguarded it left ``_build_snapshot_sync`` as a raw PermissionError
    that api/admin_db.py, which catches BackupError only, turned into a 500 with no
    operator-facing reason.
    """
    staging_root = tmp_path / "data" / "tmp"
    staging_root.mkdir(parents=True)
    staging_root.chmod(0o500)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path / "data"))
    # The system temp dir is the documented last-resort fallback; take it away too, so
    # this test observes the no-writable-root outcome rather than the fallback. It has to
    # be a path that cannot be CREATED either — a merely missing directory under tmp_path
    # would just be mkdir'd into existence.
    monkeypatch.setattr(tempfile, "tempdir", str(staging_root / "unreachable"))
    _install_fake_pg_dump(monkeypatch, tmp_path / "bin")

    try:
        with pytest.raises(BackupError, match="stage the snapshot"):
            await build_snapshot(
                backup_dir=tmp_path / "backups",
                db_url="postgresql://u:p@localhost:5432/cb",
                vault_key="test-vault-key",
                uploads_dir=uploads_dir,
                cb_version="0.1.2",
            )
    finally:
        staging_root.chmod(0o700)
