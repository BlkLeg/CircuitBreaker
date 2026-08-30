"""PostgreSQL daily backup service.

Runs pg_dump on the configured database and stores compressed .sql.gz files
under $CB_DATA_DIR/backups/ (or $BACKUP_DIR if explicitly set).
Old files are pruned based on the db_backup_retention_days setting (default: 30).
"""

import gzip
import logging
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.db.session import SessionLocal, db_url

_logger = logging.getLogger(__name__)

# _data_dir: CB_DATA_DIR is set by the Makefile (dev) and native installer.
# Docker sets it to /app/data. Falls back to /var/lib/circuitbreaker.
_data_dir = Path(os.environ.get("CB_DATA_DIR", "/var/lib/circuitbreaker"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(_data_dir / "backups")))

# Block size for the streamed dump. Matches backup/snapshot.py and backup/verify.py.
_STREAM_BLOCK = 1024 * 1024

# Suffix for a dump that is still being written. Deliberately does NOT match the
# `cb-*.sql.gz` glob that _prune_old_backups and latest_backup_info use, so a partial
# file can never be mistaken for a restorable backup.
_PARTIAL_SUFFIX = ".part"

# How old a leftover partial has to be before the next run deletes it. A SIGKILL — the
# OOM this module's streaming exists to avoid, a `docker restart`, a supervisord kill —
# runs no `finally`, so without a sweep every kill leaks a database-sized file onto the
# volume pgdata lives on. Six hours is far longer than any plausible pg_dump and short
# enough that leakage stays bounded at roughly one file.
_PARTIAL_MAX_AGE_SECONDS = 6 * 3600


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


def backup_postgres() -> None:
    """Create a compressed pg_dump snapshot."""
    if not shutil.which("pg_dump"):
        _logger.warning("pg_dump not found — skipping scheduled backup")
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_stale_partials()
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    out_path = BACKUP_DIR / f"cb-{stamp}.sql.gz"
    part_path = out_path.with_name(out_path.name + _PARTIAL_SUFFIX)
    err_path = BACKUP_DIR / f"cb-{stamp}.err"

    try:
        # Streamed in fixed blocks, never buffered whole. `subprocess.run(...,
        # capture_output=True)` materialised the ENTIRE dump as one Python bytes object
        # before a byte of it was compressed, so a 1 GB database was a 1 GB resident
        # allocation inside a container capped at 2 GB — and this is the DAILY job
        # (registered in main.py's scheduler, also reachable from POST /admin/db/backup),
        # so it took the whole application down on a schedule. Do not restore
        # capture_output; the identical rewrite lives in backup/snapshot.py.
        #
        # stderr goes to a FILE, not a pipe. Draining stdout to EOF while stderr is an
        # undrained 64 KB pipe deadlocks pg_dump the first time it is chatty — the
        # obvious "just add stderr=PIPE" is that deadlock, and a hung daily job is a
        # backup that silently stops existing.
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
                    raise OSError("pg_dump stdout pipe was not created")
                with stdout, gzip.open(part_path, "wb") as f:
                    for block in iter(lambda: stdout.read(_STREAM_BLOCK), b""):
                        f.write(block)
                returncode = proc.wait()
            except BaseException:
                # The backup volume filling up mid-dump raises here. Reap the child
                # instead of leaving a pg_dump holding a database connection open until
                # the interpreter happens to collect it.
                proc.kill()
                proc.wait()
                raise
        if returncode != 0:
            raise subprocess.CalledProcessError(returncode, "pg_dump", stderr=err_path.read_bytes())

        # Rename only after a clean exit. Streaming puts bytes on disk before the exit
        # status is known, and a truncated dump carrying the real `cb-*.sql.gz` name
        # would become latest_backup_info()'s answer and the newest file retention keeps
        # — an operator would find out it was truncated while restoring from it.
        part_path.replace(out_path)
        size_kb = out_path.stat().st_size // 1024
        _logger.info("DB backup written: %s (%d KB)", out_path.name, size_kb)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        _logger.error("pg_dump failed: %s", stderr)
        return
    except OSError as exc:
        _logger.error("DB backup failed: %s", exc)
        return
    finally:
        part_path.unlink(missing_ok=True)
        err_path.unlink(missing_ok=True)

    _prune_old_backups()


def _sweep_stale_partials() -> None:
    """Delete the scratch files a killed backup run leaves behind.

    See _PARTIAL_MAX_AGE_SECONDS. Both globs are narrow on purpose: they must never
    match `cb-*.sql.gz`, which is a finished, restorable backup. Never fatal — a backup
    that cannot tidy up is still worth taking.
    """
    cutoff = datetime.now(tz=UTC).timestamp() - _PARTIAL_MAX_AGE_SECONDS
    for pattern in (f"cb-*.sql.gz{_PARTIAL_SUFFIX}", "cb-*.err"):
        for path in BACKUP_DIR.glob(pattern):
            try:
                if not path.is_file() or path.stat().st_mtime >= cutoff:
                    continue
                path.unlink(missing_ok=True)
                _logger.warning(
                    "Swept DB backup scratch file from an interrupted run: %s", path.name
                )
            except OSError as exc:
                _logger.warning("Could not sweep DB backup scratch file %s: %s", path.name, exc)


def _prune_old_backups() -> None:
    """Delete backup files older than the configured retention period."""
    db: Session = SessionLocal()
    try:
        from app.db.models import AppSettings

        row = db.query(AppSettings).first()
        retention_days = getattr(row, "db_backup_retention_days", None) or 30
    except Exception:
        retention_days = 30
    finally:
        db.close()

    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    for f in sorted(BACKUP_DIR.glob("cb-*.sql.gz")):
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
        if mtime < cutoff:
            f.unlink(missing_ok=True)
            _logger.info("Pruned old backup: %s", f.name)


def latest_backup_info() -> dict | None:
    """Return metadata for the most recent backup file, or None."""
    if not BACKUP_DIR.exists():
        return None
    files = sorted(BACKUP_DIR.glob("cb-*.sql.gz"), reverse=True)
    if not files:
        return None
    f = files[0]
    return {
        "filename": f.name,
        "size_mb": round(f.stat().st_size / 1_048_576, 2),
        "created_at": datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat(),
        "path": str(f),
    }


async def run_full_snapshot(db: Session) -> Path:
    """Orchestrate a full-state backup snapshot.

    Steps:
    1. Resolve the vault key through vault_service.load_vault_key(db)
    2. Read AppSettings from DB (backup dirs, S3 config, retention counts)
    3. Build snapshot tarball via backup.snapshot.build_snapshot()
    4. Prune local snapshots via backup.pruner.prune_local()
    5. If S3 configured: decrypt S3 secret, upload tarball, prune remote

    Args:
        db: Synchronous SQLAlchemy session.

    Returns:
        Path to the newly created snapshot tarball.

    Raises:
        BackupError: If snapshot creation fails.
        RuntimeError: If no vault key can be resolved.
    """
    import os

    from app.db.models import AppSettings
    from app.services.backup.pruner import prune_local, prune_remote
    from app.services.backup.s3_client import BackupS3Settings, S3Client
    from app.services.backup.snapshot import BackupError, build_snapshot  # noqa: F401
    from app.services.vault_service import load_vault_key

    # Not os.environ["CB_VAULT_KEY"]. Two of this function's three callers — the daily
    # scheduler job and the admin endpoint — run inside the server process, which resolved
    # the key at boot and exported it. The third does not: `cb backup` reaches this through
    # `docker exec ... python -m app.cli snapshot create`, a fresh process that sees the
    # container's *creation* environment rather than the entrypoint's exports or the key
    # the server settled on. On a standard install those differ — the installer generates
    # one key into the container environment, OOBE generates another, writes it to
    # $CB_DATA_DIR/.env and encrypts every credential with it — so reading the environment
    # archived a key that decrypts nothing, and the restore then wrote it over the only
    # copy of the real one. load_vault_key() is the same chain main.py's phase 7 runs:
    # environment cross-checked against AppSettings.vault_key_hash, then $CB_DATA_DIR/.env,
    # then the legacy database column.
    vault_key = (load_vault_key(db) or "").strip()
    if not vault_key:
        raise RuntimeError(
            "No vault key could be resolved (checked CB_VAULT_KEY, $CB_DATA_DIR/.env and "
            "the database) — a snapshot without it cannot restore a single encrypted column"
        )

    settings = db.query(AppSettings).first()
    if settings is None:
        settings = AppSettings(id=1)

    cb_version = os.environ.get("CB_VERSION", "unknown")
    uploads_dir = _data_dir / "uploads"

    tarball = await build_snapshot(
        backup_dir=BACKUP_DIR,
        db_url=db_url,
        vault_key=vault_key,
        uploads_dir=uploads_dir,
        cb_version=cb_version,
    )

    keep_local = (
        settings.backup_local_retention_count
        if settings.backup_local_retention_count is not None
        else 7
    )
    prune_local(BACKUP_DIR, keep=keep_local)

    # S3 upload is always an encrypted derivative. The local v1 tarball remains
    # available for backward-compatible restores; plaintext never leaves disk.
    if settings.backup_s3_bucket:
        from app.services.backup.age_encryption import encrypt_for_upload

        secret_key = ""
        if settings.backup_s3_secret_key_enc:
            try:
                from app.services.credential_vault import get_vault

                secret_key = get_vault().decrypt(settings.backup_s3_secret_key_enc)
            except Exception as exc:
                _logger.warning(
                    "Could not decrypt S3 secret key: %s", exc
                )  # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501

        s3_settings = BackupS3Settings(
            bucket=settings.backup_s3_bucket,
            access_key_id=settings.backup_s3_access_key_id or "",
            secret_access_key=secret_key,
            region=settings.backup_s3_region or "us-east-1",
            endpoint_url=settings.backup_s3_endpoint_url or None,
            prefix=settings.backup_s3_prefix or "circuitbreaker/backups/",
        )
        client = S3Client(s3_settings)
        encrypted = encrypt_for_upload(tarball, settings.backup_age_recipient)
        try:
            await client.upload(encrypted)
        finally:
            encrypted.unlink(missing_ok=True)

        keep_remote = (
            settings.backup_s3_retention_count
            if settings.backup_s3_retention_count is not None
            else 30
        )
        await prune_remote(client, keep=keep_remote)

    # Publish completion event for other subscribers (e.g. notifications) to react to
    try:
        from app.core.subjects import BACKUP_SNAPSHOT_COMPLETED
        from app.services.proxmox_client import _publish

        await _publish(
            BACKUP_SNAPSHOT_COMPLETED,
            {
                "filename": tarball.name,
                "size_mb": round(tarball.stat().st_size / 1_048_576, 2),
                "s3_uploaded": bool(settings.backup_s3_bucket),
            },
        )
    except Exception:
        pass  # NATS unavailable — non-fatal

    return tarball
