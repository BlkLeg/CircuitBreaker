"""Phase 2 tests — audit log retention purge."""

from datetime import timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.time import utcnow
from app.db.models import AppSettings, Log


@pytest.fixture(autouse=True)
def _patch_session_local(db_engine):
    """Redirect SessionLocal in the log_purge module to use the test DB."""
    import app.db.session as _db_session
    import app.services.log_purge as _purge_mod

    test_session = sessionmaker(bind=db_engine)
    orig_session = _db_session.SessionLocal
    orig_purge = _purge_mod.SessionLocal

    _db_session.SessionLocal = test_session
    _purge_mod.SessionLocal = test_session
    yield
    _db_session.SessionLocal = orig_session
    _purge_mod.SessionLocal = orig_purge


def _seed_settings(db, retention_days=7):
    db.add(AppSettings(id=1, audit_log_retention_days=retention_days))
    db.commit()


def _seed_logs(db, *, old_count=5, recent_count=3, retention_days=7):
    now = utcnow()
    cutoff = now - timedelta(days=retention_days)
    for i in range(old_count):
        db.add(
            Log(
                timestamp=cutoff - timedelta(days=i + 1),
                category="crud",
                action="old_action",
                actor="system",
            )
        )
    for i in range(recent_count):
        db.add(
            Log(
                timestamp=now - timedelta(hours=i),
                category="crud",
                action="recent_action",
                actor="system",
            )
        )
    db.commit()


def test_purge_deletes_old_entries(db):
    _seed_settings(db, retention_days=7)
    _seed_logs(db, old_count=5, recent_count=3, retention_days=7)

    assert db.query(Log).count() == 8

    from app.services.log_purge import purge_old_audit_logs

    deleted = purge_old_audit_logs()

    db.expire_all()
    assert deleted == 5
    remaining = db.query(Log).all()
    assert len(remaining) >= 3
    for log in remaining:
        if log.action != "audit_log_purge":
            assert log.action == "recent_action"


def test_purge_no_old_entries(db):
    _seed_settings(db, retention_days=90)
    _seed_logs(db, old_count=0, recent_count=3, retention_days=90)

    from app.services.log_purge import purge_old_audit_logs

    deleted = purge_old_audit_logs()

    assert deleted == 0
    db.expire_all()
    assert db.query(Log).count() == 3


def test_purge_disabled_when_zero(db):
    _seed_settings(db, retention_days=0)
    _seed_logs(db, old_count=5, recent_count=2, retention_days=0)

    from app.services.log_purge import purge_old_audit_logs

    deleted = purge_old_audit_logs()

    assert deleted == 0
    db.expire_all()
    assert db.query(Log).count() == 7


def test_audit_log_filters(client, db):
    """Verify that log API filtering works with multiple filter params."""
    now = utcnow()
    db.add(
        Log(
            timestamp=now,
            category="crud",
            action="created",
            actor="alice",
            entity_type="hardware",
            severity="info",
        )
    )
    db.add(
        Log(
            timestamp=now,
            category="settings",
            action="updated",
            actor="bob",
            entity_type="settings",
            severity="warn",
        )
    )
    db.commit()

    r = client.get("/api/v1/logs", params={"action": "created"})
    assert r.status_code == 200
    data = r.json()
    assert data["total_count"] >= 1
    assert all(log["action"] == "created" for log in data["logs"])

    r = client.get("/api/v1/logs", params={"severity": "warn"})
    assert r.status_code == 200
    data = r.json()
    assert all(log.get("severity") == "warn" or log.get("level") == "warn" for log in data["logs"])
