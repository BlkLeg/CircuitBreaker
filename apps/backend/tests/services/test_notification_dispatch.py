"""Notification worker credential handling (INC-06).

The worker runs as its own process (``workers/main.py``), which — unlike the
API — never initialized the vault. Encrypting sink secrets without fixing that
would break delivery for every provider, so both halves are pinned here: the
worker loads the vault key, and dispatch receives a decrypted config.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.db.models import NotificationRoute, NotificationSink
from tests.services.notification_worker_harness import (
    SLACK_URL,
    FakeMsg,
    attach_worker_session,
    routed_slack_sink,
)


@pytest.fixture
def worker_db(monkeypatch, db_session, app_cfg):
    """Point the worker's own SessionLocal at the rolled-back test session."""
    return attach_worker_session(monkeypatch, db_session)


@pytest.mark.asyncio
async def test_dispatch_receives_the_decrypted_webhook_url(worker_db, monkeypatch) -> None:
    from app.workers import notification_worker

    routed_slack_sink(worker_db)
    sent = AsyncMock()
    monkeypatch.setattr(notification_worker, "notify_slack", sent)

    await notification_worker.process_alert(
        FakeMsg("alert.monitor.down", {"severity": "critical", "title": "Host down"})
    )

    sent.assert_awaited_once()
    assert sent.await_args.args[0]["webhook_url"] == SLACK_URL


@pytest.mark.asyncio
async def test_dispatch_still_delivers_a_legacy_plaintext_sink(worker_db, monkeypatch) -> None:
    from app.workers import notification_worker

    sink = NotificationSink(
        name="Legacy",
        provider_type="slack",
        provider_config={"webhook_url": SLACK_URL},
        enabled=True,
    )
    worker_db.add(sink)
    worker_db.flush()
    worker_db.add(NotificationRoute(sink_id=sink.id, alert_severity="*", enabled=True))
    worker_db.commit()
    sent = AsyncMock()
    monkeypatch.setattr(notification_worker, "notify_slack", sent)

    await notification_worker.process_alert(
        FakeMsg("alert.monitor.down", {"severity": "warning", "title": "Flapping"})
    )

    assert sent.await_args.args[0]["webhook_url"] == SLACK_URL


def test_init_vault_loads_the_key_in_the_worker_process() -> None:
    from app.services.credential_vault import CredentialVault, get_vault
    from app.workers import notification_worker

    vault = get_vault()
    saved = vault._fernet
    try:
        CredentialVault.__init__(vault)
        assert vault.is_initialized is False

        notification_worker._init_vault()

        assert vault.is_initialized is True
    finally:
        vault._fernet = saved


@pytest.mark.asyncio
async def test_run_worker_initializes_the_vault_before_anything_else(monkeypatch) -> None:
    """Without this the worker cannot decrypt any sink, and every alert is dropped."""
    from app.workers import notification_worker

    called = False

    def _record() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(notification_worker, "_init_vault", _record)
    monkeypatch.setattr(notification_worker.nats_client, "connect", AsyncMock(return_value=None))
    shutdown = asyncio.Event()
    shutdown.set()

    await notification_worker.run_worker(shutdown_event=shutdown)

    assert called is True
