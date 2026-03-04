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
}


def sanitise_diff(obj):
    """Recursively walk *obj* and replace the value of any sensitive key with
    ``"***REDACTED***"``.  Safe to call on ``None``."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {
            k: "***REDACTED***"
            if any(r in k.lower() for r in REDACTED_KEYS)
            else sanitise_diff(v)
            for k, v in obj.items()
        }
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
    actor_name: str = "admin",
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

        with SessionLocal() as _db:
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
                actor_name=actor_name,
                entity_name=entity_name,
                diff=diff_str,
                severity=severity,
            )
            _db.add(entry)
            _db.commit()
    except Exception as exc:  # noqa: BLE001
        print(f"[audit] write_log failed (action={action!r}): {exc}", file=sys.stderr)
