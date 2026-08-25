"""Renewal reported success for renewals that never happened.

INC-07: `renew_certificate` caught FileNotFoundError, logged a warning, and returned the
unchanged certificate — so POST /certificates/{id}/renew answered 200 with the old expiry
and the UI showed success. The non-zero-exit path did the same. The audit log recorded
`certificate_renewed` with status "ok" either way.
"""

from __future__ import annotations

import subprocess
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


def test_missing_certbot_raises_instead_of_returning_the_old_cert(db_session, le_cert, monkeypatch):
    def _absent(*args, **kwargs):
        raise FileNotFoundError("certbot")

    monkeypatch.setattr(svc, "_run_certbot", _absent)

    with pytest.raises(svc.CertificateRenewalError) as excinfo:
        svc.renew_certificate(db_session, le_cert)

    assert "certbot" in str(excinfo.value)
    assert le_cert.expires_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_nonzero_exit_raises_and_carries_the_stderr(db_session, le_cert, monkeypatch):
    monkeypatch.setattr(
        svc,
        "_run_certbot",
        lambda *a, **k: subprocess.CompletedProcess([], 1, "", "DNS problem: NXDOMAIN"),
    )

    with pytest.raises(svc.CertificateRenewalError) as excinfo:
        svc.renew_certificate(db_session, le_cert)

    assert "NXDOMAIN" in str(excinfo.value)


def test_timeout_raises(db_session, le_cert, monkeypatch):
    def _slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="certbot", timeout=120)

    monkeypatch.setattr(svc, "_run_certbot", _slow)

    with pytest.raises(svc.CertificateRenewalError):
        svc.renew_certificate(db_session, le_cert)


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
