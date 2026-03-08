"""Centralised audit log writer — the only place in the codebase that writes to the logs table.

All log entries MUST be written through :func:`write_log`.  Direct ``Log(...)``
instantiation elsewhere in the codebase is prohibited.

Audit logs are append-only.  No update or delete path exists through this service.
"""

import json
import logging
import sys

from app.core.time import utcnow, utcnow_iso

_logger = logging.getLogger(__name__)

# Keys (substring match, case-insensitive) whose values must never reach the DB.
REDACTED_KEYS = {
    "password",
    "secret",
    "token",
    "key",
    "credential",
    "community",
    "api_key",
    "vault_key",
    "telemetry_config",
    "jwt_secret",
    "password_hash",
    "hashed_password",
}


# Sorted longest-first so that e.g. "api_key" is replaced before "key".
_SORTED_REDACTED_KEYS = sorted(REDACTED_KEYS, key=len, reverse=True)


def _mask_key(k: str) -> str:
    """Return a version of *k* with sensitive substrings replaced by '<hidden>'."""
    result = k.lower()
    for r in _SORTED_REDACTED_KEYS:
        result = result.replace(r, "<hidden>")
    return result


def sanitise_diff(obj):
    """Recursively walk *obj* and replace the value of any sensitive key with
    ``"***REDACTED***"``.  The key name is also masked so that sensitive
    substrings (e.g. 'password') do not leak into audit log strings.
    Safe to call on ``None``."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if any(r in k.lower() for r in REDACTED_KEYS):
                result[_mask_key(k)] = "***REDACTED***"
            else:
                result[k] = sanitise_diff(v)
        return result
    if isinstance(obj, list):
        return [sanitise_diff(i) for i in obj]
    return obj


def write_log(
    db,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    entity_name: str = "",
    diff: dict | None = None,
    actor_name: str = "system",
    actor_id: int | None = None,
    ip_address: str | None = None,
    severity: str = "info",
    # Legacy compatibility — passed by LoggingMiddleware
    category: str = "crud",
    level: str | None = None,
    status_code: int | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    user_agent: str | None = None,
    details: str | None = None,
    actor: str | None = None,
    actor_gravatar_hash: str | None = None,
    role_at_time: str | None = None,
    session_id: int | None = None,
) -> None:
    """Write a structured audit log entry.

    - Never raises: log failures must not abort the parent transaction.
    - Runs inside a nested try/except; on failure, prints to stderr only.
    - ``created_at_utc`` is always set by this function using :func:`utcnow_iso`.
    - ``diff`` values are sanitised before write: any key containing a sensitive
      substring is replaced with ``"***REDACTED***"`` regardless of nesting depth.
    """
    try:
        from app.db.models import Log
        from app.db.session import SessionLocal

        # Sanitise diff before persisting
        sanitised_diff = sanitise_diff(diff)
        diff_str = json.dumps(sanitised_diff) if sanitised_diff is not None else None

        # Map severity → legacy level if not provided separately
        effective_level = level if level is not None else severity
        # Map actor fields (new → legacy for backward compat with existing queries)
        effective_actor = actor if actor is not None else actor_name

        _now_iso = utcnow_iso()

        def _do_write(session):
            import hashlib

            from sqlalchemy import select

            stmt = select(Log).order_by(Log.id.desc()).limit(1)
            if session.bind.dialect.name != "sqlite":
                stmt = stmt.with_for_update()

            try:
                last_log = session.execute(stmt).scalar_one_or_none()
            except Exception:
                # Fallback if with_for_update fails
                last_log = session.execute(
                    select(Log).order_by(Log.id.desc()).limit(1)
                ).scalar_one_or_none()

            previous_hash = last_log.log_hash if last_log else None

            entry_data = {
                "timestamp": _now_iso,
                "action": action,
                "actor_id": actor_id,
                "role_at_time": role_at_time,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "diff": diff_str,
                "ip_address": ip_address,
                "previous_hash": previous_hash,
            }
            # Serialize deterministically
            payload = json.dumps(entry_data, sort_keys=True)
            log_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

            entry = Log(
                timestamp=utcnow(),
                created_at_utc=_now_iso,
                # Legacy fields
                level=effective_level,
                category=category,
                action=action,
                actor=effective_actor,
                actor_gravatar_hash=actor_gravatar_hash,
                entity_type=entity_type,
                entity_id=entity_id,
                old_value=old_value,
                new_value=new_value,
                user_agent=user_agent,
                ip_address=ip_address,
                details=details,
                status_code=status_code,
                # Structured audit fields (Feature 6)
                actor_id=actor_id,
                actor_name=effective_actor,
                entity_name=entity_name,
                diff=diff_str,
                severity=severity,
                # Phase 6.5 and 7
                session_id=session_id,
                role_at_time=role_at_time,
                previous_hash=previous_hash,
                log_hash=log_hash,
            )
            session.add(entry)
            session.commit()

        if db is not None:
            _do_write(db)
        else:
            with SessionLocal() as _db:
                _do_write(_db)
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] write_log failed (action={action!r}): {exc}", file=sys.stderr)
