"""Shared scaffolding for driving ``notification_worker`` against a test session.

The worker runs as its own process and opens sessions through its own
module-level ``SessionLocal``, so exercising it in-process means handing it the
test's rolled-back session without letting it close it.
"""

import json
from unittest.mock import AsyncMock

from app.db.models import NotificationRoute, NotificationSink
from app.services.notification_secrets import encrypt_config

SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/xoxbSECRETTOKEN"


class KeepOpenSession:
    """Hand the worker the test's session without letting it close it."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *_exc):
        return False


class FakeMsg:
    """The JetStream message shape ``process_alert`` reads."""

    def __init__(self, subject: str, payload: dict):
        self.subject = subject
        self.data = json.dumps(payload).encode()


def attach_worker_session(monkeypatch, db_session):
    """Point the worker's ``SessionLocal`` at the test session, dedup disabled."""
    from app.workers import notification_worker

    monkeypatch.setattr(notification_worker, "SessionLocal", lambda: KeepOpenSession(db_session))
    monkeypatch.setattr(notification_worker, "_is_duplicate", AsyncMock(return_value=False))
    return db_session


def routed_slack_sink(
    db_session, alert_severity: str = "*", route_enabled: bool = True
) -> NotificationSink:
    """A Slack sink with one route at the given threshold."""
    sink = NotificationSink(
        name=f"Ops Slack {alert_severity}",
        provider_type="slack",
        provider_config=encrypt_config("slack", {"webhook_url": SLACK_URL}),
        enabled=True,
    )
    db_session.add(sink)
    db_session.flush()
    db_session.add(
        NotificationRoute(sink_id=sink.id, alert_severity=alert_severity, enabled=route_enabled)
    )
    db_session.commit()
    return sink
