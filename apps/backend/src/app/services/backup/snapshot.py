"""Full-state snapshot builder.

Creates a gzip-compressed tarball containing:
  - db.sql.gz       (pg_dump output, gzip-compressed)
  - vault.key       (CB_VAULT_KEY plaintext — the tarball IS the security boundary)
  - uploads/        (recursive copy of the uploads directory)
  - config/         (native-install config files — absent on Docker/dev, skipped gracefully)
      Caddyfile     (/etc/caddy/Caddyfile)
      certs/        (/etc/caddy/certs/cert.pem + key.pem)
      .env          (/etc/circuitbreaker/.env — full env, not just vault key)
  - manifest.json   (metadata + db checksum + captured config file list)

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
    staging = Path(tempfile.mkdtemp(prefix="cb-snapshot-"))
    inner = staging / f"cb-snapshot-{stamp}"
    inner.mkdir()
    dest = backup_dir / tarball_name

    try:
        # 1. pg_dump → db.sql.gz + compute sha256
        db_gz_path = inner / "db.sql.gz"
        proc = subprocess.run(  # noqa: S603
            ["pg_dump", "--no-password"],
            env=_pg_env_from_url(db_url),
            capture_output=True,
            check=True,
        )
        raw = proc.stdout
        with gzip.open(db_gz_path, "wb") as f:
            f.write(raw)
        db_checksum = hashlib.sha256(db_gz_path.read_bytes()).hexdigest()

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
            "config/Caddyfile": Path("/etc/caddy/Caddyfile"),
            "config/certs/cert.pem": Path("/etc/caddy/certs/cert.pem"),
            "config/certs/key.pem": Path("/etc/caddy/certs/key.pem"),
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
        vault_key: Raw value of CB_VAULT_KEY — stored verbatim in the tarball.
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
