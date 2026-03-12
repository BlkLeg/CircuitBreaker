from unittest.mock import MagicMock

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.scheduler import (
    get_scheduler,
    set_scheduler_instance,
    shutdown_scheduler,
    start_scheduler,
)
from app.db.models import AppSettings, User
from app.services import auth_service


def _mock_db(user_count: int, cfg: AppSettings):
    db = MagicMock()
    user_query = MagicMock()
    user_query.count.return_value = user_count
    settings_query = MagicMock()
    settings_query.first.return_value = cfg

    def _query(model):
        if model is User:
            return user_query
        if model is AppSettings:
            return settings_query
        raise AssertionError(f"unexpected model {model}")

    db.query.side_effect = _query
    return db


def test_bootstrap_status_needs_bootstrap_when_oobe_incomplete():
    """auth_enabled=False (OOBE marker not set) means bootstrap is still needed."""
    cfg = AppSettings()
    cfg.jwt_secret = "already-generated"
    cfg.auth_enabled = False
    db = _mock_db(user_count=0, cfg=cfg)

    status = auth_service.bootstrap_status(db)
    assert status.needs_bootstrap is True
    assert status.user_count == 0


def test_bootstrap_status_complete_after_oobe_marker_set():
    """auth_enabled=True (OOBE marker) means bootstrap is done."""
    cfg = AppSettings()
    cfg.jwt_secret = "already-generated"
    cfg.auth_enabled = True
    db = _mock_db(user_count=1, cfg=cfg)

    status = auth_service.bootstrap_status(db)
    assert status.needs_bootstrap is False
    assert status.user_count == 1


def test_scheduler_helpers_use_bound_runtime_instance():
    runtime_scheduler = MagicMock(spec=AsyncIOScheduler)
    runtime_scheduler.running = False

    set_scheduler_instance(runtime_scheduler)
    assert get_scheduler() is runtime_scheduler

    start_scheduler()
    runtime_scheduler.start.assert_called_once()

    runtime_scheduler.running = True
    shutdown_scheduler()
    runtime_scheduler.shutdown.assert_called_once_with(wait=False)
