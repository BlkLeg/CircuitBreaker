"""PostgreSQL daily backup service.

Runs pg_dump on the configured database and stores compressed .sql.gz files
under /app/data/backups/. Old files are pruned based on the
db_backup_retention_days setting (default: 30).

Only activated when the database dialect is PostgreSQL — SQLite installs are
skipped silently (SQLite files are already on a persistent volume).
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

from app.db.session import SessionLocal, db_url, is_sqlite

_logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/app/data/backups"))


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
    """Create a compressed pg_dump snapshot.  No-op for SQLite installs."""
    if is_sqlite:
        return

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
