"""Email notification sink delivery (INC-02).

The finding this file exists for: ``notify_email`` read ``smtp_host`` / ``smtp_port``
/ ``user`` / ``pass`` out of the sink's ``provider_config``, but the sink form has
never collected any of them — so ``hostname`` was always ``""`` and every alert was
dropped. The *test* button meanwhile used the global ``AppSettings`` SMTP config, so
it reported success while delivery failed. ``notify_email`` had no test coverage
anywhere, which is why the disagreement survived.

These tests pin the two halves back together: delivery goes through the same global
SMTP settings the test button uses, and a sink that cannot deliver says so instead
of failing silently.

``aiosmtplib`` is faked at the module boundary rather than at ``SmtpService._connect``
so the real connect logic — implicit TLS on 465, STARTTLS on 587, vault-decrypted
login — is exercised rather than stubbed over.
"""

import json
from unittest.mock import AsyncMock

import pytest

from app.db.models import AppSettings, NotificationRoute, NotificationSink
from app.services.notification_secrets import encrypt_config

_TO = "oncall@example.com"
_SMTP_PASSWORD = "smtp-s3cret"


class _FakeSMTP:
    """Records what a real aiosmtplib.SMTP would have been asked to do."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.connected = False
        self.started_tls = False
        self.login_args = None
        self.sent = []
        self.quit_called = False

    async def connect(self):
        self.connected = True

    async def starttls(self):
        self.started_tls = True

    async def login(self, username, password):
        self.login_args = (username, password)

    async def send_message(self, msg, sender=None):
        self.sent.append((msg, sender))

    async def quit(self):
        self.quit_called = True


class _FakeAiosmtplib:
    """Stand-in for the aiosmtplib module, holding the last SMTP built."""

    def __init__(self):
        self.last = None

    def SMTP(self, **kwargs):  # noqa: N802 — mirrors aiosmtplib's class name
        self.last = _FakeSMTP(**kwargs)
        return self.last


class _KeepOpenSession:
    """Hand the worker the test's session without letting it close it."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *_exc):
        return False


class _FakeMsg:
    def __init__(self, subject: str, payload: dict):
        self.subject = subject
        self.data = json.dumps(payload).encode()


@pytest.fixture
def fake_smtp(monkeypatch):
    """Replace the aiosmtplib module inside smtp_service, not SmtpService itself."""
    from app.services import smtp_service

    fake = _FakeAiosmtplib()
    monkeypatch.setattr(smtp_service, "aiosmtplib", fake)
    return fake


@pytest.fixture
def worker_db(monkeypatch, db_session, app_cfg):
    """Point the worker's own SessionLocal at the rolled-back test session."""
    from app.workers import notification_worker

    monkeypatch.setattr(notification_worker, "SessionLocal", lambda: _KeepOpenSession(db_session))
    monkeypatch.setattr(notification_worker, "_is_duplicate", AsyncMock(return_value=False))
    return db_session


def _configure_smtp(db_session, *, host: str = "smtp.example.com", port: int = 587) -> AppSettings:
    from app.services.credential_vault import get_vault

    cfg = db_session.query(AppSettings).first()
    if cfg is None:
        cfg = AppSettings(id=1)
        db_session.add(cfg)
    cfg.smtp_host = host
    cfg.smtp_port = port
    cfg.smtp_username = "notifier@example.com"
    cfg.smtp_password_enc = get_vault().encrypt(_SMTP_PASSWORD)
    cfg.smtp_from_email = "circuitbreaker@example.com"
    cfg.smtp_from_name = "Circuit Breaker"
    cfg.smtp_tls = True
    db_session.commit()
    return cfg


def _routed_email_sink(db_session, config: dict | None = None) -> NotificationSink:
    sink = NotificationSink(
        name="On-call Email",
        provider_type="email",
        provider_config=encrypt_config("email", {"to": _TO} if config is None else config),
        enabled=True,
    )
    db_session.add(sink)
    db_session.flush()
    db_session.add(NotificationRoute(sink_id=sink.id, alert_severity="*", enabled=True))
    db_session.commit()
    return sink


@pytest.mark.asyncio
async def test_an_email_sink_delivers_through_the_global_smtp_settings(
    worker_db, fake_smtp
) -> None:
    """The sink supplies only the recipient; the connection comes from AppSettings."""
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg("alert.monitor.down", {"severity": "critical", "title": "Host down"})
    )

    smtp = fake_smtp.last
    assert smtp is not None, "no SMTP connection was opened"
    assert smtp.kwargs["hostname"] == "smtp.example.com"
    assert smtp.kwargs["port"] == 587
    assert smtp.started_tls is True
    assert smtp.login_args == ("notifier@example.com", _SMTP_PASSWORD)

    assert len(smtp.sent) == 1
    msg, sender = smtp.sent[0]
    assert msg["To"] == _TO
    assert sender == "circuitbreaker@example.com"


@pytest.mark.asyncio
async def test_the_alert_subject_carries_the_severity_and_title(worker_db, fake_smtp) -> None:
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg("alert.monitor.down", {"severity": "critical", "title": "Host down"})
    )

    msg, _ = fake_smtp.last.sent[0]
    assert "CRITICAL" in msg["Subject"]
    assert "Host down" in msg["Subject"]


def _part_text(msg, subtype: str) -> str:
    """Decoded body of the first ``text/<subtype>`` part.

    ``as_string()`` is useless here: MIMEText with a utf-8 charset base64-encodes
    the payload, so the literal alert text never appears in the raw message.
    """
    for part in msg.walk():
        if part.get_content_type() == f"text/{subtype}":
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError(f"no text/{subtype} part in message")


@pytest.mark.asyncio
async def test_the_alert_body_carries_the_message(worker_db, fake_smtp) -> None:
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg(
            "alert.monitor.down",
            {"severity": "warning", "title": "Latency high", "message": "p99 exceeded 800ms"},
        )
    )

    msg, _ = fake_smtp.last.sent[0]
    assert "p99 exceeded 800ms" in _part_text(msg, "plain")
    assert "p99 exceeded 800ms" in _part_text(msg, "html")


@pytest.mark.asyncio
async def test_an_alert_is_sent_as_both_plain_text_and_html(worker_db, fake_smtp) -> None:
    """Alerts are read on phones and in terminal clients; HTML-only is unreadable there."""
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg("alert.monitor.down", {"severity": "critical", "title": "Host down"})
    )

    msg, _ = fake_smtp.last.sent[0]
    subtypes = {p.get_content_type() for p in msg.walk()}
    assert "text/plain" in subtypes
    assert "text/html" in subtypes


@pytest.mark.asyncio
async def test_alert_text_is_escaped_in_the_html_body(worker_db, fake_smtp) -> None:
    """Alert titles carry probe- and operator-authored text; it must not become markup."""
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg(
            "alert.monitor.down",
            {
                "severity": "critical",
                "title": "<img src=x onerror=alert(1)>",
                "message": "host <b>db01</b> down",
            },
        )
    )

    html = _part_text(fake_smtp.last.sent[0][0], "html")
    assert "<img src=x" not in html
    assert "&lt;img src=x" in html
    assert "<b>db01</b>" not in html


@pytest.mark.asyncio
async def test_delivery_fails_loudly_when_smtp_is_not_configured(worker_db, fake_smtp) -> None:
    """An unconfigured host used to mean a connect to ""; it must name the real cause."""
    _configure_smtp(worker_db, host="")

    from app.workers import notification_worker

    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        await notification_worker.notify_email({"to": _TO}, "Host down", "body", "critical")

    assert fake_smtp.last is None, "no connection should be attempted without a host"


@pytest.mark.asyncio
async def test_delivery_fails_loudly_when_the_sink_has_no_recipient(worker_db, fake_smtp) -> None:
    _configure_smtp(worker_db)

    from app.workers import notification_worker

    with pytest.raises(RuntimeError, match="no recipient"):
        await notification_worker.notify_email({}, "Host down", "body", "critical")

    assert fake_smtp.last is None


@pytest.mark.asyncio
async def test_a_multiline_alert_title_still_delivers(worker_db, fake_smtp) -> None:
    """Python's generator rejects an embedded newline in a header — the alert would
    fail to send entirely. Collapse the subject instead of losing the alert."""
    _configure_smtp(worker_db)
    _routed_email_sink(worker_db)

    from app.workers import notification_worker

    await notification_worker.process_alert(
        _FakeMsg(
            "alert.monitor.down",
            {"severity": "critical", "title": "Host down\r\nBcc: attacker@evil.test"},
        )
    )

    msg, _ = fake_smtp.last.sent[0]
    subject = msg["Subject"]
    assert "\n" not in subject and "\r" not in subject
    assert "Host down" in subject
    # The message still flattens — proof the header guard is not merely deferred.
    msg.as_bytes()
