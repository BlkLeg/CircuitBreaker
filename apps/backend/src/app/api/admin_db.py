"""Admin endpoints for database health and backup management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException  # noqa: F401 — Depends used for get_db
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.session import engine, get_db
from app.services.db_backup import (
    BACKUP_DIR,  # noqa: F401 — module-level name required for monkeypatching in tests
    backup_postgres,
    latest_backup_info,
    run_full_snapshot,
)

router = APIRouter(tags=["admin-db"])


# ── Pydantic schemas ───────────────────────────────────────────────────────────


class SnapshotInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    filename: str
    size_mb: float
    created_at: datetime
    s3_key: str | None = None


class SnapshotListResponse(BaseModel):
    snapshots: list[SnapshotInfo]


class BackupSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    backup_s3_bucket: str | None
    backup_s3_endpoint_url: str | None
    backup_s3_access_key_id: str | None
    backup_s3_secret_key_set: bool
    backup_s3_region: str
    backup_s3_prefix: str
    backup_s3_retention_count: int
    backup_local_retention_count: int


class BackupSettingsUpdate(BaseModel):
    backup_s3_bucket: str | None = None
    backup_s3_endpoint_url: str | None = None
    backup_s3_access_key_id: str | None = None
    backup_s3_secret_key: str | None = None  # plaintext; None = leave unchanged; "" = clear
    backup_s3_region: str | None = None
    backup_s3_prefix: str | None = None
    backup_s3_retention_count: int | None = None
    backup_local_retention_count: int | None = None


class DbHealthResponse(BaseModel):
    status: str
    dialect: str
    alembic_version: str | None = None
    db_size_mb: float | None = None
    # PostgreSQL-only
    connections_active: int | None = None
    connections_max: int | None = None
    backup_last_at: str | None = None
    backup_last_filename: str | None = None
    backup_last_size_mb: float | None = None


@router.get("/db/health", response_model=DbHealthResponse)
def db_health(_: Any = require_role("admin")) -> DbHealthResponse:
    """Return database health metrics. Admin-only."""
    dialect = "postgresql"

    # Alembic version
    alembic_version: str | None = None
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).fetchone()
            if row:
                alembic_version = row[0]
    except Exception:
        pass

    # DB size
    db_size_mb: float | None = None
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT pg_database_size(current_database())")).fetchone()
            if row:
                db_size_mb = round(row[0] / 1_048_576, 2)
    except Exception:
        pass

    # PostgreSQL connection stats
    connections_active: int | None = None
    connections_max: int | None = None
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE state != 'idle'")
            ).fetchone()
            if row:
                connections_active = row[0]
            row2 = conn.execute(text("SHOW max_connections")).fetchone()
            if row2:
                connections_max = int(row2[0])
    except Exception:
        pass

    # Backup info
    info = latest_backup_info()
    backup_last_at = info["created_at"] if info else None
    backup_last_filename = info["filename"] if info else None
    backup_last_size_mb = info["size_mb"] if info else None

    return DbHealthResponse(
        status="healthy",
        dialect=dialect,
        alembic_version=alembic_version,
        db_size_mb=db_size_mb,
        connections_active=connections_active,
        connections_max=connections_max,
        backup_last_at=backup_last_at,
        backup_last_filename=backup_last_filename,
        backup_last_size_mb=backup_last_size_mb,
    )


@router.post("/db/backup")
def trigger_backup(_: Any = require_role("admin")) -> dict[str, Any]:
    """Trigger an immediate pg_dump backup."""
    backup_postgres()
    info = latest_backup_info()
    return {"status": "ok", "backup": info}


# ── Snapshot endpoints ─────────────────────────────────────────────────────────


@router.post("/db/snapshot", response_model=SnapshotInfo)
async def trigger_snapshot(
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> SnapshotInfo:
    """Trigger a full-state backup snapshot."""
    from app.services.backup.snapshot import BackupError

    try:
        tarball = await run_full_snapshot(db)
    except BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    stat = tarball.stat()
    return SnapshotInfo(
        filename=tarball.name,
        size_mb=round(stat.st_size / (1024 * 1024), 2),
        created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        s3_key=None,
    )


@router.get("/db/snapshots", response_model=SnapshotListResponse)
def list_snapshots(
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> SnapshotListResponse:
    """List local snapshot tarballs."""
    import app.api.admin_db as _self

    snapshots = []
    for path in sorted(_self.BACKUP_DIR.glob("cb-snapshot-*.tar.gz")):
        stat = path.stat()
        snapshots.append(
            SnapshotInfo(
                filename=path.name,
                size_mb=round(stat.st_size / (1024 * 1024), 2),
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                s3_key=None,
            )
        )
    return SnapshotListResponse(snapshots=snapshots)


# ── Backup settings endpoints ──────────────────────────────────────────────────


@router.get("/settings/backup", response_model=BackupSettingsResponse)
def get_backup_settings(
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> BackupSettingsResponse:
    """Return current backup S3 settings (secret key masked)."""
    from app.db.models import AppSettings

    settings = db.query(AppSettings).first()
    if settings is None:
        settings = AppSettings(id=1)
    return BackupSettingsResponse(
        backup_s3_bucket=settings.backup_s3_bucket,
        backup_s3_endpoint_url=settings.backup_s3_endpoint_url,
        backup_s3_access_key_id=settings.backup_s3_access_key_id,
        backup_s3_secret_key_set=bool(settings.backup_s3_secret_key_enc),
        backup_s3_region=settings.backup_s3_region or "us-east-1",
        backup_s3_prefix=settings.backup_s3_prefix or "circuitbreaker/backups/",
        backup_s3_retention_count=settings.backup_s3_retention_count or 30,
        backup_local_retention_count=settings.backup_local_retention_count or 7,
    )


@router.put("/settings/backup", response_model=BackupSettingsResponse)
def update_backup_settings(
    update: BackupSettingsUpdate,
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> BackupSettingsResponse:
    """Update backup S3 settings (PATCH semantics: None fields left unchanged)."""
    from app.db.models import AppSettings
    from app.services.credential_vault import get_vault

    settings = db.query(AppSettings).first()
    if settings is None:
        settings = AppSettings(id=1)
        db.add(settings)

    if update.backup_s3_bucket is not None:
        settings.backup_s3_bucket = update.backup_s3_bucket or None
    if update.backup_s3_endpoint_url is not None:
        settings.backup_s3_endpoint_url = update.backup_s3_endpoint_url or None
    if update.backup_s3_access_key_id is not None:
        settings.backup_s3_access_key_id = update.backup_s3_access_key_id or None
    if update.backup_s3_secret_key is not None:
        if update.backup_s3_secret_key == "":
            settings.backup_s3_secret_key_enc = None
        else:
            settings.backup_s3_secret_key_enc = get_vault().encrypt(update.backup_s3_secret_key)
    if update.backup_s3_region is not None:
        settings.backup_s3_region = update.backup_s3_region
    if update.backup_s3_prefix is not None:
        settings.backup_s3_prefix = update.backup_s3_prefix
    if update.backup_s3_retention_count is not None:
        settings.backup_s3_retention_count = update.backup_s3_retention_count
    if update.backup_local_retention_count is not None:
        settings.backup_local_retention_count = update.backup_local_retention_count

    db.commit()
    db.refresh(settings)
    return BackupSettingsResponse(
        backup_s3_bucket=settings.backup_s3_bucket,
        backup_s3_endpoint_url=settings.backup_s3_endpoint_url,
        backup_s3_access_key_id=settings.backup_s3_access_key_id,
        backup_s3_secret_key_set=bool(settings.backup_s3_secret_key_enc),
        backup_s3_region=settings.backup_s3_region or "us-east-1",
        backup_s3_prefix=settings.backup_s3_prefix or "circuitbreaker/backups/",
        backup_s3_retention_count=settings.backup_s3_retention_count or 30,
        backup_local_retention_count=settings.backup_local_retention_count or 7,
    )


@router.post("/settings/backup/test")
async def test_backup_connection(
    db: Session = Depends(get_db),
    _: Any = require_role("admin"),
) -> dict[str, str | None]:
    """Test S3 connection by uploading a 1-byte probe object."""
    from app.db.models import AppSettings
    from app.services.backup.s3_client import BackupS3Settings, S3Client, S3Error
    from app.services.credential_vault import get_vault

    settings = db.query(AppSettings).first()
    if settings is None or not settings.backup_s3_bucket:
        raise HTTPException(status_code=400, detail="S3 bucket not configured")

    secret_key = ""
    if settings.backup_s3_secret_key_enc:
        try:
            secret_key = get_vault().decrypt(settings.backup_s3_secret_key_enc)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not decrypt S3 secret: {exc}",
            ) from exc

    s3_settings = BackupS3Settings(
        bucket=settings.backup_s3_bucket,
        access_key_id=settings.backup_s3_access_key_id or "",
        secret_access_key=secret_key,
        region=settings.backup_s3_region or "us-east-1",
        endpoint_url=settings.backup_s3_endpoint_url or None,
        prefix=settings.backup_s3_prefix or "circuitbreaker/backups/",
    )
    client = S3Client(s3_settings)
    try:
        await client.probe()
    except S3Error as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "status": "ok",
        "bucket": settings.backup_s3_bucket,
        "endpoint": settings.backup_s3_endpoint_url,
    }
