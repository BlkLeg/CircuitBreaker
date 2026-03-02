"""Logs API — query, clear, and stream audit log entries.

Audit logs are append-only. No update or delete endpoints exist by design.
"""
import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.security import require_write_auth
from app.core.time import elapsed_seconds as _elapsed_seconds
from sqlalchemy.orm import Session
from sqlalchemy import select, func, or_, distinct

from app.db.session import get_db, SessionLocal
from app.db.models import Log
from app.schemas.logs import LogEntry, LogsResponse

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogsResponse)
def list_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    category: Optional[str] = None,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    level: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    sort: Optional[str] = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    _order = Log.timestamp.asc() if sort == "asc" else Log.timestamp.desc()
    q = select(Log).order_by(_order)
    count_q = select(func.count()).select_from(Log)

    if start_time:
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp >= dt)
            count_q = count_q.where(Log.timestamp >= dt)
        except ValueError:
            pass

    if end_time:
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp <= dt)
            count_q = count_q.where(Log.timestamp <= dt)
        except ValueError:
            pass

    if category:
        q = q.where(Log.category == category)
        count_q = count_q.where(Log.category == category)

    if action:
        q = q.where(Log.action == action)
        count_q = count_q.where(Log.action == action)

    if entity_type:
        q = q.where(Log.entity_type == entity_type)
        count_q = count_q.where(Log.entity_type == entity_type)

    if entity_id is not None:
        q = q.where(Log.entity_id == entity_id)
        count_q = count_q.where(Log.entity_id == entity_id)

    # Support both `level` (legacy) and `severity` (new) filter params
    sev_filter = severity or level
    if sev_filter:
        q = q.where(or_(Log.severity == sev_filter, Log.level == sev_filter))
        count_q = count_q.where(or_(Log.severity == sev_filter, Log.level == sev_filter))

    if search:
        pattern = f"%{search}%"
        search_filter = or_(
            Log.action.ilike(pattern),
            Log.entity_type.ilike(pattern),
            Log.entity_name.ilike(pattern),
            Log.details.ilike(pattern),
            Log.new_value.ilike(pattern),
        )
        q = q.where(search_filter)
        count_q = count_q.where(search_filter)

    total_count = db.execute(count_q).scalar_one()
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()

    logs_out = []
    for row in rows:
        entry = LogEntry.model_validate(row)
        entry.elapsed_seconds = _elapsed_seconds(row.created_at_utc) if row.created_at_utc else None
        logs_out.append(entry)

    return LogsResponse(
        logs=logs_out,
        total_count=total_count,
        has_more=(offset + limit) < total_count,
    )


@router.get("/actions")
def list_actions(db: Session = Depends(get_db)):
    """Return the distinct set of action strings present in the logs table.
    Used by the frontend to populate the action filter dropdown dynamically.
    """
    rows = db.execute(
        select(distinct(Log.action)).where(Log.action.isnot(None)).order_by(Log.action)
    ).scalars().all()
    return {"actions": rows}


@router.delete("")
def clear_logs(db: Session = Depends(get_db), _=Depends(require_write_auth)):
    deleted = db.execute(select(Log)).scalars().all()
    count = len(deleted)
    for row in deleted:
        db.delete(row)
    db.commit()
    return {"deleted": count}


@router.get("/stream")
async def stream_logs(since: Optional[str] = None):
    """Server-Sent Events endpoint — streams new log entries since a given timestamp."""

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError:
            since_dt = None

    async def event_generator():
        # Use a mutable reference so we can update across iterations
        last_dt = since_dt

        # Send a keepalive comment immediately so the client knows the connection is alive
        yield ": keepalive\n\n"

        while True:
            await asyncio.sleep(2)
            try:
                with SessionLocal() as db:
                    q = select(Log).order_by(Log.timestamp.asc())
                    if last_dt is not None:
                        q = q.where(Log.timestamp > last_dt)
                    else:
                        q = q.limit(0)  # Nothing to send until we have a reference point
                    rows = db.execute(q).scalars().all()

                for row in rows:
                    payload = json.dumps({
                        "id": row.id,
                        "timestamp": row.timestamp.isoformat(),
                        "created_at_utc": row.created_at_utc,
                        "elapsed_seconds": _elapsed_seconds(row.created_at_utc) if row.created_at_utc else None,
                        "level": row.level,
                        "severity": row.severity or row.level,
                        "category": row.category,
                        "action": row.action,
                        "actor": row.actor,
                        "actor_name": row.actor_name,
                        "actor_gravatar_hash": row.actor_gravatar_hash,
                        "entity_type": row.entity_type,
                        "entity_id": row.entity_id,
                        "entity_name": row.entity_name,
                        "diff": row.diff,
                        "old_value": row.old_value,
                        "new_value": row.new_value,
                        "user_agent": row.user_agent,
                        "ip_address": row.ip_address,
                        "details": row.details,
                    })
                    yield f"data: {payload}\n\n"
                    if last_dt is None or row.timestamp > last_dt:
                        last_dt = row.timestamp
            except Exception:
                # Never crash the SSE stream
                yield ": error\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
