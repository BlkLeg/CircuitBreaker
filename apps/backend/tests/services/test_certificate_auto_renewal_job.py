"""The nightly renewal job, now that renewal raises.

`renew_certificate` used to swallow every failure and return the unchanged certificate, so
the job could not fail. It raises now (INC-07), which makes two properties load-bearing that
nothing had ever tested:

  * one certificate's failure must not abandon the rest of the fleet — the loop is the only
    thing standing between a single bad domain and every other certificate expiring;
  * a failure must leave a record an operator can find. This runs at 03:45 with nobody
    watching, and a log line in a container that has since restarted is not a record.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import Certificate
from app.services import certificate_service as svc


@pytest.fixture(autouse=True)
def _no_alerts(monkeypatch):
    """The expiry-alert half publishes to NATS; it is not what these tests are about."""
    monkeypatch.setattr(svc, "_publish_alert", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_publish_renewal", lambda *a, **k: None)


def _expiring(db_session, domain: str) -> Certificate:
    cert = Certificate(
        domain=domain,
        type="selfsigned",
        cert_pem="-- old --",
        key_pem="-- old --",
        expires_at=datetime.now(UTC) + timedelta(days=3),
        auto_renew=True,
    )
    db_session.add(cert)
    db_session.flush()
    return cert


def test_one_failure_does_not_abandon_the_rest(db_session, app_cfg, monkeypatch):
    bad = _expiring(db_session, "bad.example.com")
    good = _expiring(db_session, "good.example.com")
    original = good.expires_at

    real = svc.renew_certificate

    def _renew(db, cert):
        if cert.id == bad.id:
            raise svc.CertificateRenewalError("DNS problem: NXDOMAIN")
        return real(db, cert)

    monkeypatch.setattr(svc, "renew_certificate", _renew)

    renewed = svc.check_and_renew_expiring(db_session)

    db_session.refresh(good)
    assert renewed == 1
    assert good.expires_at > original


def test_a_failed_renewal_is_recorded_where_an_operator_will_find_it(
    db_session, app_cfg, monkeypatch
):
    """`log_audit` writes through `write_log` on its own session, so the assertion is on
    the call rather than on a row this test's transaction would roll back anyway."""
    from app.services import log_service

    written: list[dict] = []
    monkeypatch.setattr(log_service, "write_log", lambda **kw: written.append(kw))

    cert = _expiring(db_session, "bad2.example.com")
    monkeypatch.setattr(
        svc,
        "renew_certificate",
        lambda db, c: (_ for _ in ()).throw(svc.CertificateRenewalError("DNS problem: NXDOMAIN")),
    )

    svc.check_and_renew_expiring(db_session)

    entry = next(e for e in written if e["action"] == "certificate_auto_renew_failed")
    assert entry["severity"] == "error"
    assert "NXDOMAIN" in entry["details"]
    assert str(cert.id) in entry["entity_type"]


def test_a_certificate_that_is_not_due_is_left_alone(db_session, app_cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "renew_certificate", lambda db, c: calls.append(c.id))
    far = Certificate(
        domain="far.example.com",
        type="selfsigned",
        cert_pem="-- old --",
        key_pem="-- old --",
        expires_at=datetime.now(UTC) + timedelta(days=300),
        auto_renew=True,
    )
    db_session.add(far)
    db_session.flush()

    svc.check_and_renew_expiring(db_session)

    assert far.id not in calls
