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
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    out_path = BACKUP_DIR / f"cb-{stamp}.sql.gz"

    try:
        proc = subprocess.run(  # noqa: S603
            ["pg_dump", "--no-password"],
            env=_pg_env_from_url(db_url),
            capture_output=True,
            check=True,
        )
        with gzip.open(out_path, "wb") as f:
            f.write(proc.stdout)
        size_kb = out_path.stat().st_size // 1024
        _logger.info("DB backup written: %s (%d KB)", out_path.name, size_kb)
    except subprocess.CalledProcessError as exc:
        _logger.error("pg_dump failed: %s", exc.stderr.decode(errors="replace"))
        return

    _prune_old_backups()


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
    1. Read vault_key from os.environ["CB_VAULT_KEY"]
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
        RuntimeError: If CB_VAULT_KEY is not set.
    """
    import os

    from app.db.models import AppSettings
    from app.services.backup.pruner import prune_local, prune_remote
    from app.services.backup.s3_client import BackupS3Settings, S3Client
    from app.services.backup.snapshot import BackupError, build_snapshot  # noqa: F401

    vault_key = os.environ.get("CB_VAULT_KEY", "")
    if not vault_key:
        raise RuntimeError("CB_VAULT_KEY environment variable is not set")

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

    # S3 upload (optional — only if bucket is configured)
    if settings.backup_s3_bucket:
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
        await client.upload(tarball)

        keep_remote = (
            settings.backup_s3_retention_count
            if settings.backup_s3_retention_count is not None
            else 30
        )
        await prune_remote(client, keep=keep_remote)

    # Publish completion event so webhook rules can trigger on backup success
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
