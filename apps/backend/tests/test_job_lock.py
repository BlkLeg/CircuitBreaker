"""Tests for distributed job lock (advisory lock)."""

from unittest.mock import MagicMock, patch


def test_lock_id_deterministic():
    """Same name and args produce the same lock id."""
    from app.core.job_lock import _lock_id_for

    a = _lock_id_for("discovery_purge")
    b = _lock_id_for("discovery_purge")
    assert a == b
    assert _lock_id_for("discovery_profile", 1) != _lock_id_for("discovery_profile", 2)
    assert isinstance(a, int)


def test_try_advisory_lock_acquired():
    """try_advisory_lock returns True when DB returns true."""
    from app.core.job_lock import try_advisory_lock

    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (True,)
    got = try_advisory_lock(db, 12345)
    assert got is True
    db.execute.assert_called_once()


def test_try_advisory_lock_not_acquired():
    """try_advisory_lock returns False when DB returns false."""
    from app.core.job_lock import try_advisory_lock

    db = MagicMock()
    db.execute.return_value.fetchone.return_value = (False,)
    got = try_advisory_lock(db, 12345)
    assert got is False


def test_run_with_advisory_lock_skips_job_when_lock_not_acquired():
    """When lock is not acquired, job_fn is not called."""
    from app.core.job_lock import run_with_advisory_lock

    job_ran = []

    def job_fn():
        job_ran.append(1)

    with patch("app.core.job_lock.SessionLocal") as mock_factory:
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = (False,)
        mock_factory.return_value = mock_db

        run_with_advisory_lock("test_job", job_fn=job_fn)

    assert job_ran == []
    mock_db.close.assert_called_once()


def test_run_with_advisory_lock_runs_job_when_lock_acquired():
    """When lock is acquired, job_fn is called and lock is released."""
    from app.core.job_lock import run_with_advisory_lock

    job_ran = []

    def job_fn():
        job_ran.append(1)

    with patch("app.core.job_lock.SessionLocal") as mock_factory:
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.side_effect = [(True,), (True,)]
        mock_factory.return_value = mock_db

        run_with_advisory_lock("test_job", job_fn=job_fn)

    assert job_ran == [1]
    assert mock_db.execute.call_count >= 2
    mock_db.close.assert_called_once()
