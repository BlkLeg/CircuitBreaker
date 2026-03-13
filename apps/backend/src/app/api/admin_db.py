"""Admin endpoints for database health and backup management."""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.rbac import require_role
from app.db.session import engine
from app.services.db_backup import backup_postgres, latest_backup_info

router = APIRouter(tags=["admin-db"])


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
def db_health(_=require_role("admin")):
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
def trigger_backup(_=require_role("admin")):
    """Trigger an immediate pg_dump backup."""
    backup_postgres()
    info = latest_backup_info()
    return {"status": "ok", "backup": info}
