"""Single source of truth for all timestamp generation in the app.

Every module that needs the current time or timestamp formatting imports
from here — no bare datetime.now() calls elsewhere.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime object."""
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO 8601 string with timezone offset.

    Format: 2026-03-01T22:45:00.123456+00:00
    """
    return utcnow().isoformat()


def elapsed_seconds(since_iso: str) -> float | None:
    """Given a stored ISO 8601 string, return seconds elapsed since then.

    Returns None if the string is unparseable.
    """
    try:
        dt = datetime.fromisoformat(since_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (utcnow() - dt).total_seconds()
    except (ValueError, TypeError):
        return None
