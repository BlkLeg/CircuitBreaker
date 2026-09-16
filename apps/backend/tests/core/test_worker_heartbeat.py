"""Unit tests for worker heartbeat path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.worker_heartbeat import heartbeat_data_dir, heartbeat_path, touch_heartbeat


def test_heartbeat_path_uses_cb_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    assert heartbeat_path("worker-discovery") == tmp_path / "worker-discovery.healthy"


def test_heartbeat_path_defaults_to_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CB_DATA_DIR", raising=False)
    assert heartbeat_data_dir() == Path("/data")
    assert heartbeat_path("worker-notification") == Path("/data/worker-notification.healthy")


def test_touch_heartbeat_writes_epoch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    touch_heartbeat("worker-discovery")
    path = tmp_path / "worker-discovery.healthy"
    assert path.is_file()
    float(path.read_text(encoding="utf-8"))


def test_rejects_invalid_worker_name() -> None:
    with pytest.raises(ValueError):
        heartbeat_path("../escape")
