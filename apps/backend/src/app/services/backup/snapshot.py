"""Full-state snapshot builder.

Creates a gzip-compressed tarball containing:
  - db.sql.gz       (pg_dump output, gzip-compressed)
  - vault.key       (the vault key in plaintext — the tarball IS the security boundary)
  - uploads/        (recursive copy of the uploads directory)
  - config/         (native-install config files — absent on Docker/dev, skipped gracefully)
      nginx/        (/etc/nginx/conf.d/circuitbreaker.conf — the reverse proxy the
                     installer configures; see deploy/setup.sh:841)
      .env          (/etc/circuitbreaker/.env — full env, not just vault key)
  - manifest.json   (format version, install mode, metadata + db checksum + captured
                     config file list)

TLS material is deliberately NOT captured here. The installer places it under
``${CB_DATA_DIR}/tls`` (deploy/setup.sh:812) and certificate activation writes those same
two files from the database, so the certificates already travel in the database dump.
Copying the plaintext private key a second time would widen the blast radius of an archive
that is already a secret, for no recovery benefit.

The tarball is set to mode 0600 immediately after creation.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import anyio

_logger = logging.getLogger(__name__)

CB_VERSION = os.environ.get("CB_VERSION", "unknown")

SNAPSHOT_FORMAT_VERSION = 1

# Block size for every streaming read in this module. Matches verify.py's convention.
_STREAM_BLOCK = 1024 * 1024

# How old an abandoned staging tree has to be before the next snapshot removes it.
# Comfortably longer than any plausible pg_dump + uploads copy, short enough that a
# repeatedly killed job leaks roughly one tree rather than one per run.
_STAGING_ORPHAN_MAX_AGE_SECONDS = 6 * 3600


class BackupError(RuntimeError):
    """Raised when snapshot creation fails."""


def _pg_env_from_url(url: str) -> dict[str, str]:
    """Parse a postgresql:// URL into pg_dump environment variables."""
    parsed = urlparse(url)
    env = dict(os.environ)
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = parsed.username
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    if parsed.path and parsed.path != "/":
        env["PGDATABASE"] = parsed.path.lstrip("/")
    return env


def _staging_roots() -> list[Path]:
    """Candidate scratch roots for snapshot assembly, best first.

    NOT the system temp dir. In the shipped mono container /tmp is a 100 MB tmpfs on a
    read-only root filesystem (docker-compose.yml), and the staging tree holds the whole
    pg_dump plus an uncompressed copy of uploads/ — so staging there turns the daily
    snapshot into ENOSPC the moment an install has any real data in it. Stage on the
    persistent data volume instead, which docker/entrypoint-mono.sh already creates as
    ``${CB_DATA_DIR}/tmp``. Same reasoning, same shape as
    ``certificate_service._certbot_tmp_root``.

    The default matches ``db_backup._data_dir`` (the native installer's data root), and
    the system temp dir stays on the list as a last resort so native and dev installs
    keep working where that path is not writable — their TMPDIR is already persistent.
    Do not "simplify" this back to a bare ``mkdtemp()``: the missing ``dir=`` is the
    entire bug.
    """
    data_root = Path(os.environ.get("CB_DATA_DIR", "/var/lib/circuitbreaker")) / "tmp"
    system_root = Path(tempfile.gettempdir())
    if data_root == system_root:
        return [data_root]
    return [data_root, system_root]


def _make_staging_dir() -> Path:
    """Create the staging directory, or fail with a reason an operator can act on.

    Both steps are guarded, not only the mkdir. ``mkdir(exist_ok=True)`` does NOT raise
    when the directory already exists but is not writable, which is exactly the state
    docker/entrypoint-mono.sh leaves behind when its ``chown -R`` on the data volume is
    not permitted — it warns and carries on. The failure then surfaces from ``mkdtemp``,
    and unguarded it escaped ``_build_snapshot_sync`` as a raw PermissionError:
    api/admin_db.py catches BackupError only, so ``POST /admin/db/snapshot`` answered
    500 with nothing an operator could act on. ENOSPC on the data volume is the same
    shape. Keep the whole creation inside the guard.
    """
    failures: list[str] = []
    for root in _staging_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="cb-snapshot-", dir=str(root)))
        except OSError as exc:
            failures.append(f"{root}: {exc}")
    raise BackupError(
        "no writable directory to stage the snapshot in (" + "; ".join(failures) + ")"
    )


def _sweep_orphan_staging(root: Path) -> None:
    """Delete staging trees left behind by a snapshot that was killed outright.

    This is the cost of moving staging off the container's tmpfs. /tmp was wiped by
    Docker on every container restart, so an interrupted snapshot cleaned up after
    itself for free; the persistent data volume is never wiped by anything. The
    ``finally`` in _build_snapshot_sync covers every ordinary failure but NOT SIGKILL —
    which is precisely the failure the streaming rewrite above is about, plus
    `docker restart` and supervisord kills. Each orphan holds an uncompressed copytree
    of uploads/ plus the dump, on the same volume as pgdata, so without a sweep the
    fix for a 100 MB tmpfs ENOSPC becomes an unbounded disk fill under the database.
    Do not remove this without putting an equivalent sweep in the boot path.

    Age-based, because a concurrent snapshot's staging dir is live and must survive:
    everything a running build writes goes into ``inner/``, so a staging dir's own mtime
    stays at creation time and the cutoff only has to exceed one pg_dump. Never fatal —
    a snapshot that cannot tidy up is still worth taking.
    """
    cutoff = datetime.now(tz=UTC).timestamp() - _STAGING_ORPHAN_MAX_AGE_SECONDS
    for path in root.glob("cb-snapshot-*"):
        try:
            if not path.is_dir() or path.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(path, ignore_errors=True)
            _logger.warning("Swept orphaned snapshot staging dir: %s", path.name)
        except OSError as exc:
            _logger.warning("Could not sweep snapshot staging dir %s: %s", path.name, exc)


def _build_snapshot_sync(
    backup_dir: Path,
    db_url: str,
    vault_key: str,
    uploads_dir: Path,
    cb_version: str,
) -> Path:
    """Synchronous implementation — run via anyio.to_thread.run_sync."""
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")
    tarball_name = f"cb-snapshot-{stamp}.tar.gz"
    staging = _make_staging_dir()
    # Our own staging dir is seconds old, so it is never a candidate for its own sweep.
    _sweep_orphan_staging(staging.parent)
    inner = staging / f"cb-snapshot-{stamp}"
    inner.mkdir()
    dest = backup_dir / tarball_name

    try:
        # 1. pg_dump → db.sql.gz + compute sha256
        #
        # Streamed in fixed blocks, never buffered whole. `subprocess.run(...,
        # capture_output=True)` materialised the ENTIRE dump as one Python bytes object
        # before a byte of it was compressed, so a 1 GB database was a 1 GB resident
        # allocation inside a container capped at 2 GB — the daily snapshot job took the
        # whole application down with it. Same for `read_bytes()` on the finished archive.
        # Keep both loops; do not restore capture_output or a whole-file read.
        #
        # stderr goes to a FILE, not a pipe. Draining stdout to EOF while stderr is an
        # undrained 64 KB pipe deadlocks pg_dump the first time it is chatty — the
        # obvious "just add stderr=PIPE" is that deadlock. err_path lives under `staging`,
        # which the `finally` below already removes.
        db_gz_path = inner / "db.sql.gz"
        err_path = staging / "pg_dump.err"
        with err_path.open("wb") as errf:
            proc = subprocess.Popen(  # noqa: S603
                ["pg_dump", "--no-password"],
                env=_pg_env_from_url(db_url),
                stdout=subprocess.PIPE,
                stderr=errf,
            )
            try:
                stdout = proc.stdout
                if stdout is None:  # stdout=PIPE guarantees one; narrow for type checkers
                    raise BackupError("pg_dump stdout pipe was not created")
                with stdout, gzip.open(db_gz_path, "wb") as f:
                    for block in iter(lambda: stdout.read(_STREAM_BLOCK), b""):
                        f.write(block)
                returncode = proc.wait()
            except BaseException:
                # The staging volume filling up mid-dump is exactly the failure this
                # rewrite exists to survive, and it raises here. Reap the child instead
                # of leaving a pg_dump holding a database connection open until the
                # interpreter happens to collect it.
                proc.kill()
                proc.wait()
                raise
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, "pg_dump", stderr=err_path.read_bytes())

        # The checksum covers the COMPRESSED bytes: verify.py hashes exactly these when it
        # validates an archive, so hashing the raw SQL instead would fail every snapshot
        # ever taken, including the one an operator is trying to restore from.
        digest = hashlib.sha256()
        with db_gz_path.open("rb") as fh:
            for block in iter(lambda: fh.read(_STREAM_BLOCK), b""):
                digest.update(block)
        db_checksum = digest.hexdigest()

        # 2. vault.key
        (inner / "vault.key").write_text(vault_key, encoding="utf-8")

        # 3. uploads
        if uploads_dir.exists():
            shutil.copytree(uploads_dir, inner / "uploads")
            uploads_count = sum(1 for _ in (inner / "uploads").rglob("*") if _.is_file())
        else:
            (inner / "uploads").mkdir()
            uploads_count = 0

        # 4. Config files (native install only — skip gracefully if absent)
        _CONFIG_PATHS: dict[str, Path] = {
            "config/nginx/circuitbreaker.conf": Path("/etc/nginx/conf.d/circuitbreaker.conf"),
            "config/.env": Path("/etc/circuitbreaker/.env"),
        }
        config_files: dict[str, Path] = {
            arc: src for arc, src in _CONFIG_PATHS.items() if src.exists()
        }
        for arc_name, src_path in config_files.items():
            dest_path = inner / arc_name
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)

        # 5. manifest.json
        manifest = {
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "install_mode": os.environ.get("CB_INSTALL_MODE", "unknown"),
            "cb_version": cb_version,
            "created_at": datetime.now(tz=UTC).isoformat(),
            "db_name": _pg_env_from_url(db_url).get("PGDATABASE", "circuitbreaker"),
            "uploads_count": uploads_count,
            "db_checksum_sha256": db_checksum,
            "config_files": list(config_files.keys()),
        }
        (inner / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        # 6. Pack tarball
        backup_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(dest, "w:gz") as tf:
            tf.add(inner, arcname=f"cb-snapshot-{stamp}")

        # 7. Restrict permissions
        os.chmod(dest, 0o600)

        _logger.info("Snapshot created: %s (%d KB)", dest.name, dest.stat().st_size // 1024)
        return dest

    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise BackupError(f"pg_dump failed: {stderr}") from exc
    except Exception as exc:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise BackupError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


async def build_snapshot(
    backup_dir: Path,
    db_url: str,
    vault_key: str,
    uploads_dir: Path,
    cb_version: str,
) -> Path:
    """Build a full-state snapshot tarball.

    Args:
        backup_dir: Directory to write the tarball into.
        db_url: PostgreSQL connection URL (postgresql://...).
        vault_key: The vault key the database is encrypted with, as resolved by the
            caller through ``vault_service.load_vault_key`` — stored verbatim in the
            tarball. Not read from the environment here: see ``db_backup.run_full_snapshot``.
        uploads_dir: Path to the uploads directory to archive.
        cb_version: Application version string for manifest.

    Returns:
        Path to the created .tar.gz file.

    Raises:
        BackupError: If pg_dump fails or any I/O error occurs. Partial files
            are cleaned up before raising.
    """
    return await anyio.to_thread.run_sync(
        lambda: _build_snapshot_sync(backup_dir, db_url, vault_key, uploads_dir, cb_version)
    )
