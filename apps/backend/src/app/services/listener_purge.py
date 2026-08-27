"""listener_events retention purge — scheduled daily by the APScheduler job.

`listener_events` is the only discovery table fed directly by unauthenticated
LAN traffic: every mDNS advertisement and every SSDP datagram that clears the
listener's admission gate becomes a row, and until B13 nothing ever deleted one.
A quiet home network writes a few thousand rows a week and a noisy one writes
orders of magnitude more, so the table was an unbounded, attacker-influenced
consumer of the same volume the database itself lives on.

The rows are a *recency* signal — "this service was advertising on this address
lately" — consumed by discovery to seed candidates. Nothing treats them as an
audit trail or as the system of record for anything, so a row past the window
has no reader; it is only cost. Fourteen days is deliberately the long end of
the 7–14 range so a fortnightly-scanned network still sees its own devices.

Shaped like `services/log_purge.py` and `monitoring/probe_reconcile.py`'s purge:
a testable function taking a session, plus the zero-argument entry point an
APScheduler job registers.

NOT YET WIRED. `main.py` registers `purge_old_scan_results` (03:00),
`audit_log_purge` (03:15) and `monitor_probe_run_purge` (03:20) and nothing
here, so on this tree `listener_events` still grows without bound and this
module is dead code that happens to be tested. Whoever adds the registration
should keep it off 03:30, which already carries three other jobs. Until then the
retention half of B13 is open, and no test in `tests/test_listener_hardening.py`
claims otherwise — see
`test_the_zero_argument_scheduler_entrypoint_actually_purges`.

The retention window is env-only rather than an `AppSettings` column like
`audit_log_retention_days`, which means an operator changes it with a restart
rather than in the UI. That is a deliberate smaller footprint — a settings
column is a migration and a model change — and it is why the window is read
through a function on every call instead of frozen into a module constant at
import: a bad value must not be able to take the process down from inside a
startup import, and a corrected value must not need a code change to take
effect.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ListenerEvent
from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)

#: Fourteen days is deliberately the long end of the 7–14 range so a
#: fortnightly-scanned network still sees its own devices.
DEFAULT_RETENTION_DAYS = 14

RETENTION_DAYS_ENV = "CB_LISTENER_EVENT_RETENTION_DAYS"


def listener_event_retention_days() -> int:
    """The retention window, read fresh from the environment on every call.

    Read here rather than at import on purpose. The obvious
    `int(os.getenv(...))` at module scope runs inside the scheduler-registration
    import in `main.py`'s startup, so a typo in one env var is not a bad window —
    it is a process that will not boot, with a `ValueError` from a purge module
    as the only clue. A malformed value falls back to the default and says so.

    A value of 0 or less disables the purge, matching how
    `audit_log_retention_days` reads in `log_purge.py`: an operator who asks for
    no retention gets no retention, but has to ask for it explicitly.
    """
    raw = os.getenv(RETENTION_DAYS_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_RETENTION_DAYS
    try:
        return int(raw)
    except ValueError:
        _logger.warning(
            "%s=%r is not an integer; falling back to %d days",
            RETENTION_DAYS_ENV,
            raw,
            DEFAULT_RETENTION_DAYS,
        )
        return DEFAULT_RETENTION_DAYS


def purge_listener_events(db: Session, *, now: datetime | None = None) -> int:
    """Delete listener events past the retention window. Owns its commit."""
    days = listener_event_retention_days()
    if days <= 0:
        _logger.debug("Listener event retention disabled (days=%d); skipping purge", days)
        return 0

    cutoff = (now or utcnow()) - timedelta(days=days)
    result = db.execute(delete(ListenerEvent).where(ListenerEvent.seen_at < cutoff))
    deleted = int(result.rowcount or 0)  # type: ignore[attr-defined]
    db.commit()
    if deleted:
        _logger.info("Purged %d listener event(s) older than %d days", deleted, days)
    return deleted


def purge_old_listener_events() -> int:
    """The zero-argument shape the APScheduler retention job in `main.py` takes."""
    with SessionLocal() as db:
        return purge_listener_events(db)


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "RETENTION_DAYS_ENV",
    "listener_event_retention_days",
    "purge_listener_events",
    "purge_old_listener_events",
]
