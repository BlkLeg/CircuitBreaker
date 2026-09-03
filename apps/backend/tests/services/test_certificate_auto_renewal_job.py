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


def _serve_real_certificate(monkeypatch, tmp_path, pem: str) -> object:
    """Point `_live_nginx_cert_pem` at *pem* and hand back the served file.

    The gate reads the served bytes to derive a pin, so this has to be a
    parseable certificate rather than a placeholder string.
    """
    served = tmp_path / "tls"
    served.mkdir(exist_ok=True)
    chain = served / "fullchain.pem"
    chain.write_text(pem)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    return chain


def test_an_unattended_renewal_will_not_strand_the_fleet(
    db_session, app_cfg, factories, self_signed_certificate, monkeypatch, tmp_path
):
    """C1. Renewing a self-signed certificate mints a fresh keypair, so a
    fresh pin. Writing it to disk underneath agents pinned to the old one
    breaks every dial path they have — including the update channel that
    would otherwise deliver a fix, which is what makes it unrecoverable
    without physical access to each host.

    The convergence gate that prevents this used to live in the admin
    activation route, and this job does not go through that route. It runs at
    03:45 with nobody watching, which is the worst place to discover that a
    mechanism was never on the path.

    The renewal itself must still succeed: refusing to renew would trade a
    stranded fleet for an expired certificate, on a schedule.
    """
    factories.agent(status="active")
    self_signed_certificate.is_active = True
    self_signed_certificate.auto_renew = True
    self_signed_certificate.expires_at = datetime.now(UTC) + timedelta(days=3)
    db_session.flush()
    original_pem = self_signed_certificate.cert_pem
    chain = _serve_real_certificate(monkeypatch, tmp_path, original_pem)

    renewed = svc.check_and_renew_expiring(db_session)

    db_session.refresh(self_signed_certificate)
    assert renewed == 1, "the renewal itself must still happen"
    assert self_signed_certificate.cert_pem != original_pem, "renewed bytes belong in the database"
    assert chain.read_text() == original_pem, "nothing may reach the disk while agents are pinned"


def test_a_blocked_activation_leaves_a_record_an_operator_can_find(
    db_session, app_cfg, factories, self_signed_certificate, monkeypatch, tmp_path
):
    """A renewal that silently declines to take effect is indistinguishable
    from one that worked, until the certificate expires. The audit row is the
    only thing that tells an operator a rotation is now owed."""
    from app.services import log_service

    written: list[dict] = []
    monkeypatch.setattr(log_service, "write_log", lambda **kw: written.append(kw))

    factories.agent(status="active")
    self_signed_certificate.is_active = True
    self_signed_certificate.auto_renew = True
    self_signed_certificate.expires_at = datetime.now(UTC) + timedelta(days=3)
    db_session.flush()
    _serve_real_certificate(monkeypatch, tmp_path, self_signed_certificate.cert_pem)

    svc.check_and_renew_expiring(db_session)

    entry = next(e for e in written if e["action"] == "certificate_activation_blocked")
    assert entry["severity"] == "error"
    assert self_signed_certificate.domain in entry["details"]
    assert "rotation" in entry["details"]


def test_a_renewal_with_no_agents_still_activates(
    db_session, app_cfg, self_signed_certificate, monkeypatch, tmp_path
):
    """The gate must not become a brake on installs that have no fleet.

    Most Circuit Breaker installs never enrol an agent at all. For them a
    self-signed renewal has nobody to strand, and a certificate that renews
    but never reaches nginx would expire in front of the user.
    """
    self_signed_certificate.is_active = True
    self_signed_certificate.auto_renew = True
    self_signed_certificate.expires_at = datetime.now(UTC) + timedelta(days=3)
    db_session.flush()
    original_pem = self_signed_certificate.cert_pem
    chain = _serve_real_certificate(monkeypatch, tmp_path, original_pem)

    svc.check_and_renew_expiring(db_session)

    db_session.refresh(self_signed_certificate)
    assert chain.read_text() == self_signed_certificate.cert_pem
    assert chain.read_text() != original_pem
