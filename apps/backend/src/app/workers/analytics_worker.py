"""Analytics background worker: capacity forecast, right-sizing, flap detection."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.job_lock import run_with_advisory_lock
from app.db.session import SessionLocal
from app.services import failed_message_service
from app.services.intelligence.analytics import (
    run_capacity_forecast,
    run_flap_detection,
    run_right_sizing,
)
from app.services.intelligence.retention import run_retention_executor

_logger = logging.getLogger(__name__)


def _run_analytics_impl() -> None:
    db = SessionLocal()
    try:
        run_capacity_forecast(db)
        run_right_sizing(db)
        run_flap_detection(db)
        db.commit()
        _logger.info("Analytics job completed")
    except Exception:
        db.rollback()
        _logger.exception("Analytics job failed")
        raise
    finally:
        db.close()


def run_analytics_job() -> None:
    run_with_advisory_lock("analytics_job", job_fn=_run_analytics_impl)


def run_retention_job() -> None:
    """Downsample warm-window telemetry and purge cold data."""

    def _impl() -> None:
        db = SessionLocal()
        try:
            run_retention_executor(db)
            db.commit()
        except Exception:
            db.rollback()
            _logger.exception("Retention job failed")
            raise
        finally:
            db.close()

        # `failed_messages` had no retention at all: `discard` keeps the row by
        # design, so the operator action that "clears" a flood left every
        # payload-bearing row behind forever. Only resolved rows are pruned — a
        # still-parked message is unfinished work, however old.
        #
        # Separate session and separate try, deliberately: this is housekeeping
        # for a different table, and it must not be able to fail the telemetry
        # retention above or be rolled back by it.
        pruned_db = SessionLocal()
        try:
            pruned = failed_message_service.prune_resolved(
                pruned_db, older_than_days=failed_message_service.RESOLVED_RETENTION_DAYS
            )
            if pruned:
                _logger.info("[analytics_worker] pruned %d resolved failed_messages", pruned)
        except SQLAlchemyError:
            pruned_db.rollback()
            _logger.exception("[analytics_worker] failed_messages prune failed")
        finally:
            pruned_db.close()

    run_with_advisory_lock("retention_job", job_fn=_impl)
