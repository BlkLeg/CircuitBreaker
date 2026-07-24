"""Tests for NativeProbePlugin.sync() — two live call sites use different config
shapes (see app/workers/integration_worker.py:_sync_one and
app/workers/integration_sync_worker.py:_run_sync_impl); both must work."""

from __future__ import annotations

from unittest.mock import patch

from app.db.models import IntegrationMonitor
from app.integrations.native_probe import NativeProbePlugin


def test_sync_accepts_worker_style_dict_config(db_session, factories):
    """integration_worker._sync_one passes a plain dict (no `.id`) plus `integration_id`
    as a kwarg — sync() must not assume `config` is an ORM row with attribute access."""
    intg = factories.integration(type="native")
    db_session.add(
        IntegrationMonitor(
            integration_id=intg.id,
            external_id="svc-1",
            name="test svc",
            probe_type="tcp",
            probe_target="127.0.0.1",
            probe_port=80,
        )
    )
    db_session.flush()

    plugin = NativeProbePlugin()
    config: dict = {"base_url": ""}

    with patch("app.integrations.native_probe._probe", return_value=("up", 1.0)):
        results = plugin.sync(config, db=db_session, integration_id=intg.id)

    assert len(results) == 1
    assert results[0].external_id == "svc-1"
    assert results[0].status == "up"


def test_sync_accepts_orm_row_config(db_session, factories):
    """integration_sync_worker._run_sync_impl passes the Integration ORM row
    directly (no integration_id kwarg) — sync() must fall back to config.id."""
    intg = factories.integration(type="native")
    db_session.add(
        IntegrationMonitor(
            integration_id=intg.id,
            external_id="svc-2",
            name="test svc 2",
            probe_type="tcp",
            probe_target="127.0.0.1",
            probe_port=80,
        )
    )
    db_session.flush()

    plugin = NativeProbePlugin()

    with patch("app.integrations.native_probe._probe", return_value=("up", 1.0)):
        results = plugin.sync(intg, db=db_session)

    assert len(results) == 1
    assert results[0].external_id == "svc-2"
