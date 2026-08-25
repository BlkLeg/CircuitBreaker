"""Renewal reported success for renewals that never happened.

INC-07: `renew_certificate` caught FileNotFoundError, logged a warning, and returned the
unchanged certificate — so POST /certificates/{id}/renew answered 200 with the old expiry
and the UI showed success. The non-zero-exit path did the same. The audit log recorded
`certificate_renewed` with status "ok" either way.

Renewal now goes through the same `issue_acme_certificate` issuance does, so these drive
that seam. The conversion of each certbot failure into a typed error is tested where it
happens, in tests/services/test_acme_issuance_failures.py; what is pinned here is that
whatever comes back as a failure leaves the stored certificate untouched, and that a
renewal only changes what the server presents when it was already presenting it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models import Certificate
from app.services import certificate_service as svc


@pytest.fixture
def le_cert(db_session):
    cert = Certificate(
        domain="a.example.com",
        type="letsencrypt",
        cert_pem="-- old cert --",
        key_pem="-- old key --",
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        auto_renew=True,
    )
    db_session.add(cert)
    db_session.flush()
    return cert


def _refusing(message: str):
    def _issue(*args, **kwargs):
        raise svc.CertificateRenewalError(message)

    return _issue


def test_a_refused_issuance_raises_instead_of_returning_the_old_cert(
    db_session, le_cert, monkeypatch
):
    monkeypatch.setattr(
        svc,
        "issue_acme_certificate",
        _refusing("certbot is not available in this image"),
        raising=False,
    )

    with pytest.raises(svc.CertificateRenewalError) as excinfo:
        svc.renew_certificate(db_session, le_cert)

    assert "certbot" in str(excinfo.value)
    assert le_cert.expires_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_the_failure_reason_reaches_the_caller(db_session, le_cert, monkeypatch):
    """The operator needs the CA's own words; "renewal failed" is not actionable."""
    monkeypatch.setattr(
        svc, "issue_acme_certificate", _refusing("DNS problem: NXDOMAIN"), raising=False
    )

    with pytest.raises(svc.CertificateRenewalError) as excinfo:
        svc.renew_certificate(db_session, le_cert)

    assert "NXDOMAIN" in str(excinfo.value)


def test_a_failed_renewal_leaves_the_stored_certificate_alone(db_session, le_cert, monkeypatch):
    monkeypatch.setattr(svc, "issue_acme_certificate", _refusing("timed out"), raising=False)

    with pytest.raises(svc.CertificateRenewalError):
        svc.renew_certificate(db_session, le_cert)

    db_session.refresh(le_cert)
    assert le_cert.cert_pem == "-- old cert --"


def test_renewal_reissues_with_the_challenge_the_row_records(
    db_session, app_cfg, le_cert, monkeypatch
):
    """A renewal that fell back to HTTP-01 on an install with no public inbound would fail
    every night, and the row is the only record of how the certificate was obtained."""
    calls = []
    le_cert.acme_challenge = "dns-01"
    le_cert.acme_staging = True
    db_session.flush()

    def _issue(domain, **kwargs):
        calls.append({"domain": domain, **kwargs})
        return ("-- new cert --", "-- new key --", datetime(2030, 6, 1, tzinfo=UTC))

    monkeypatch.setattr(svc, "issue_acme_certificate", _issue, raising=False)

    svc.renew_certificate(db_session, le_cert)

    assert calls == [{"domain": "a.example.com", "challenge": "dns-01", "staging": True}]
    assert le_cert.expires_at == datetime(2030, 6, 1, tzinfo=UTC)


def test_a_legacy_row_with_no_recorded_challenge_renews_over_http01(
    db_session, app_cfg, le_cert, monkeypatch
):
    """Rows predating the column have NULL there — the default has to live in the code."""
    calls = []
    monkeypatch.setattr(
        svc,
        "issue_acme_certificate",
        lambda domain, **kw: (
            calls.append(kw)
            or ("-- new cert --", "-- new key --", datetime(2030, 6, 1, tzinfo=UTC))
        ),
        raising=False,
    )

    svc.renew_certificate(db_session, le_cert)

    assert calls[0]["challenge"] == "http-01"


def test_selfsigned_renewal_still_works(app_cfg, db_session):
    """`app_cfg` is what initialises the vault; the self-signed branch encrypts the new key."""
    cert = Certificate(
        domain="b.example.com",
        type="selfsigned",
        cert_pem="-- old --",
        key_pem="-- old --",
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        auto_renew=True,
    )
    db_session.add(cert)
    db_session.flush()

    renewed = svc.renew_certificate(db_session, cert)

    assert renewed.expires_at > datetime(2026, 1, 1, tzinfo=UTC)


# ── Activation after renewal ──────────────────────────────────────────────────
# A renewed certificate that sits in the database while nginx keeps serving the expired
# one is the whole feature failing quietly: the row says "renewed", the browser says
# "expired". Guarded on is_active in the other direction, because a renewal must never
# change *which* certificate the server presents.


@pytest.fixture
def activation_calls(monkeypatch):
    from app.services import certificate_activation as act

    calls: list[int] = []
    monkeypatch.setattr(
        act,
        "activate_certificate",
        lambda db, cert: calls.append(cert.id) or act.ActivationResult(True, True, "ok"),
    )
    return calls


def _selfsigned(db_session, domain: str, *, is_active: bool) -> Certificate:
    cert = Certificate(
        domain=domain,
        type="selfsigned",
        cert_pem="-- old --",
        key_pem="-- old --",
        expires_at=datetime(2026, 1, 1, tzinfo=UTC),
        auto_renew=True,
        is_active=is_active,
    )
    db_session.add(cert)
    db_session.flush()
    return cert


def test_renewing_the_active_certificate_reactivates_it(db_session, app_cfg, activation_calls):
    cert = _selfsigned(db_session, "act-a.example.com", is_active=True)

    svc.renew_certificate(db_session, cert)

    assert activation_calls == [cert.id]


def test_renewing_an_inactive_certificate_does_not_activate_it(
    db_session, app_cfg, activation_calls
):
    cert = _selfsigned(db_session, "act-b.example.com", is_active=False)

    svc.renew_certificate(db_session, cert)

    assert activation_calls == []


def test_a_failed_renewal_never_activates(db_session, le_cert, monkeypatch, activation_calls):
    le_cert.is_active = True
    db_session.flush()
    monkeypatch.setattr(svc, "issue_acme_certificate", _refusing("certbot failed"), raising=False)

    with pytest.raises(svc.CertificateRenewalError):
        svc.renew_certificate(db_session, le_cert)

    assert activation_calls == []


def test_a_renewal_that_cannot_be_activated_still_reports_the_renewal(
    db_session, app_cfg, monkeypatch
):
    """Written-but-not-served is a real state, and losing the renewal on top of it would
    make the next attempt re-issue a certificate that already exists."""
    from app.services import certificate_activation as act

    def _fails(db, cert):
        raise OSError("read-only file system")

    monkeypatch.setattr(act, "activate_certificate", _fails)
    cert = _selfsigned(db_session, "act-c.example.com", is_active=True)

    renewed = svc.renew_certificate(db_session, cert)

    assert renewed.expires_at > datetime(2026, 1, 1, tzinfo=UTC)
