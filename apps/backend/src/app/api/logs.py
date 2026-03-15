"""Logs API — query, clear, and stream audit log entries.

Audit logs are append-only. No update or delete endpoints exist by design.
"""

import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.core.time import elapsed_seconds as _elapsed_seconds
from app.db.models import Log, User
from app.db.session import SessionLocal, get_db
from app.schemas.logs import LogEntry, LogsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["logs"])

_RESERVED_ACTOR_NAMES = {"anonymous", "system", "api-token"}


def _profile_url(user: "User") -> str | None:
    if not user or not user.profile_photo:
        return None
    if user.profile_photo.startswith(("http://", "https://")):
        return user.profile_photo
    return f"/uploads/profiles/{user.profile_photo}"


def _actor_name_key(row: Log) -> str:
    return (row.actor_name or row.actor or "").strip().lower()


def _build_user_cache(db: Session, rows: Sequence[Log]) -> dict:
    """Return a mapping of actor_id → User for all rows that have one,
    plus a secondary name→User index for rows where actor_id is NULL
    so service-level log writes can still be enriched.
    """
    actor_ids = {row.actor_id for row in rows if row.actor_id is not None}
    actor_names = {
        _actor_name_key(row)
        for row in rows
        if row.actor_id is None
        and _actor_name_key(row)
        and _actor_name_key(row) not in _RESERVED_ACTOR_NAMES
    }

    users_by_id: dict[int, User] = {}
    users_by_name: dict[str, User] = {}

    def _index_user(user: User) -> None:
        if user.display_name:
            users_by_name.setdefault(user.display_name.strip().lower(), user)
        if user.email:
            users_by_name.setdefault(user.email.strip().lower(), user)

    if actor_ids:
        from sqlalchemy import select as _sel

        fetched = db.execute(_sel(User).where(User.id.in_(actor_ids))).scalars().all()
        users_by_id = {u.id: u for u in fetched}
        for user in fetched:
            _index_user(user)

    if actor_names:
        from sqlalchemy import select as _sel

        fallback_users = (
            db.execute(
                _sel(User).where(
                    or_(
                        func.lower(User.display_name).in_(actor_names),
                        func.lower(User.email).in_(actor_names),
                    )
                )
            )
            .scalars()
            .all()
        )
        for user in fallback_users:
            _index_user(user)

    return {"by_id": users_by_id, "by_name": users_by_name}


def _resolve_user(row: Log, cache: dict[str, dict]) -> User | None:
    user = None
    if row.actor_id is not None:
        user = cache["by_id"].get(row.actor_id)
    if user is None:
        name_key = _actor_name_key(row)
        if name_key and name_key not in _RESERVED_ACTOR_NAMES:
            user = cache["by_name"].get(name_key)
    return user


def _enrich_entry(entry: LogEntry, row: Log, cache: dict[str, dict]) -> LogEntry:
    """Populate actor_gravatar_hash and actor_profile_photo_url from the user cache."""
    user = _resolve_user(row, cache)

    if user:
        entry.actor_gravatar_hash = entry.actor_gravatar_hash or user.gravatar_hash
        entry.actor_profile_photo_url = _profile_url(user)
    return entry


@router.get("", response_model=LogsResponse)
def list_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start_time: str | None = None,
    end_time: str | None = None,
    category: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    level: str | None = None,
    severity: str | None = None,
    search: str | None = None,
    sort: str | None = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    _order = Log.timestamp.asc() if sort == "asc" else Log.timestamp.desc()
    q = select(Log).order_by(_order)
    count_q = select(func.count()).select_from(Log)

    if start_time:
        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp >= dt)
            count_q = count_q.where(Log.timestamp >= dt)
        except ValueError as exc:
            logger.debug("Invalid start_time format '%s' (ignored): %s", start_time, exc)

    if end_time:
        try:
            dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp <= dt)
            count_q = count_q.where(Log.timestamp <= dt)
        except ValueError as exc:
            logger.debug("Invalid end_time format '%s' (ignored): %s", end_time, exc)

    if category:
        q = q.where(Log.category == category)
        count_q = count_q.where(Log.category == category)

    if action:
        q = q.where(Log.action == action)
        count_q = count_q.where(Log.action == action)

    if actor:
        actor_filter = or_(Log.actor == actor, Log.actor_name == actor)
        q = q.where(actor_filter)
        count_q = count_q.where(actor_filter)

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
            Log.actor.ilike(pattern),
            Log.actor_name.ilike(pattern),
        )
        q = q.where(search_filter)
        count_q = count_q.where(search_filter)

    total_count = db.execute(count_q).scalar_one()
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()

    cache = _build_user_cache(db, rows)
    logs_out = []
    for row in rows:
        entry = LogEntry.model_validate(row)
        entry.elapsed_seconds = _elapsed_seconds(row.created_at_utc) if row.created_at_utc else None
        entry = _enrich_entry(entry, row, cache)
        logs_out.append(entry)

    return LogsResponse(
        logs=logs_out,
        total_count=total_count,
        has_more=(offset + limit) < total_count,
    )


@router.get("/actions")
def list_actions(
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    """Return the distinct set of action strings present in the logs table.
    Used by the frontend to populate the action filter dropdown dynamically.
    """
    rows = (
        db.execute(select(distinct(Log.action)).where(Log.action.isnot(None)).order_by(Log.action))
        .scalars()
        .all()
    )
    return {"actions": rows}


@router.get("/audit", response_model=LogsResponse)
def list_audit_logs(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    start_time: str | None = None,
    end_time: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    sort: str | None = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    _=require_role("admin"),
):
    """Admin-only endpoint that returns entries with category='audit'."""
    from datetime import datetime as _dt

    _order = Log.timestamp.asc() if sort == "asc" else Log.timestamp.desc()
    q = select(Log).where(Log.category == "audit").order_by(_order)
    count_q = select(func.count()).select_from(Log).where(Log.category == "audit")

    if start_time:
        try:
            dt = _dt.fromisoformat(start_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp >= dt)
            count_q = count_q.where(Log.timestamp >= dt)
        except ValueError as exc:
            logger.debug("Invalid start_time format '%s' (ignored): %s", start_time, exc)

    if end_time:
        try:
            dt = _dt.fromisoformat(end_time.replace("Z", "+00:00"))
            q = q.where(Log.timestamp <= dt)
            count_q = count_q.where(Log.timestamp <= dt)
        except ValueError as exc:
            logger.debug("Invalid end_time format '%s' (ignored): %s", end_time, exc)

    if action:
        q = q.where(Log.action == action)
        count_q = count_q.where(Log.action == action)

    if actor:
        actor_filter = or_(Log.actor == actor, Log.actor_name == actor)
        q = q.where(actor_filter)
        count_q = count_q.where(actor_filter)

    total_count = db.execute(count_q).scalar_one()
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()

    from app.core.time import elapsed_seconds as _elapsed_seconds

    cache = _build_user_cache(db, rows)
    logs_out = []
    for row in rows:
        entry = LogEntry.model_validate(row)
        entry.elapsed_seconds = _elapsed_seconds(row.created_at_utc) if row.created_at_utc else None
        entry = _enrich_entry(entry, row, cache)
        logs_out.append(entry)

    return LogsResponse(
        logs=logs_out,
        total_count=total_count,
        has_more=(offset + limit) < total_count,
    )


@router.delete("")
def clear_logs(db: Session = Depends(get_db), _=require_role("admin")):
    deleted = db.execute(select(Log)).scalars().all()
    count = len(deleted)
    for row in deleted:
        db.delete(row)
    db.commit()
    return {"deleted": count}


@router.get("/stream")
async def stream_logs(
    since: str | None = None,
    _=require_role("admin"),
):
    """Server-Sent Events endpoint — streams new log entries since a given timestamp."""

    since_dt: datetime | None = None
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

                    cache = _build_user_cache(db, rows) if rows else {"by_id": {}, "by_name": {}}

                for row in rows:
                    entry = LogEntry.model_validate(row)
                    entry.elapsed_seconds = (
                        _elapsed_seconds(row.created_at_utc) if row.created_at_utc else None
                    )
                    entry = _enrich_entry(entry, row, cache)
                    payload = json.dumps(
                        {
                            "id": entry.id,
                            "timestamp": entry.timestamp.isoformat(),
                            "created_at_utc": entry.created_at_utc,
                            "elapsed_seconds": entry.elapsed_seconds,
                            "level": entry.level,
                            "severity": entry.severity or entry.level,
                            "category": entry.category,
                            "action": entry.action,
                            "actor": entry.actor,
                            "actor_name": entry.actor_name,
                            "actor_gravatar_hash": entry.actor_gravatar_hash,
                            "actor_profile_photo_url": entry.actor_profile_photo_url,
                            "entity_type": entry.entity_type,
                            "entity_id": entry.entity_id,
                            "entity_name": entry.entity_name,
                            "diff": entry.diff,
                            "old_value": entry.old_value,
                            "new_value": entry.new_value,
                            "user_agent": entry.user_agent,
                            "ip_address": entry.ip_address,
                            "details": entry.details,
                        }
                    )
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
