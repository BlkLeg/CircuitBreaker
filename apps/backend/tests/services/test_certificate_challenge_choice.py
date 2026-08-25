"""Which ACME challenge a certificate is issued with, and that the answer survives.

``acme_service`` accepts ``challenge="dns-01"`` and ``staging=True``, and before this the
only caller passed neither — so DNS-01 was implemented capability with no way to reach it,
which is the shape of half the findings in the 1.0.0 register. The choice is per certificate
rather than per install: a domain on Cloudflare and a domain that is not can both live here.

It is stored on the row because renewal has to make the same choice again, unattended,
months later. A renewal that silently fell back to HTTP-01 on an install with no public
inbound would fail every night with a correct-looking error.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.db.models import Certificate
from app.schemas.certificate import CertificateCreate
from app.services import certificate_service as svc

_ISSUED = ("-- le cert --", "-- le key --", datetime(2030, 1, 1, tzinfo=UTC))


@pytest.fixture(autouse=True)
def _vault_ready():
    from app.services.credential_vault import get_vault

    get_vault().reinitialize(os.environ["CB_VAULT_KEY"])


@pytest.fixture
def issuer_calls(monkeypatch):
    """Record what create_certificate asks the ACME issuer for."""
    calls: list[dict] = []

    def _issue(domain, **kwargs):
        calls.append({"domain": domain, **kwargs})
        return _ISSUED

    monkeypatch.setattr(svc, "issue_acme_certificate", _issue, raising=False)
    return calls


def test_http01_is_the_default(db_session, issuer_calls):
    svc.create_certificate(
        db_session, CertificateCreate(domain="h.example.com", type="letsencrypt")
    )

    assert issuer_calls[0]["challenge"] == "http-01"
    assert issuer_calls[0]["staging"] is False


def test_dns01_reaches_the_issuer(db_session, issuer_calls):
    svc.create_certificate(
        db_session,
        CertificateCreate(domain="d1.example.com", type="letsencrypt", challenge="dns-01"),
    )

    assert issuer_calls[0]["challenge"] == "dns-01"


def test_staging_reaches_the_issuer(db_session, issuer_calls):
    """The preflight message tells an operator to test with staging; it has to be reachable."""
    svc.create_certificate(
        db_session,
        CertificateCreate(domain="s.example.com", type="letsencrypt", use_staging=True),
    )

    assert issuer_calls[0]["staging"] is True


def test_the_choice_is_stored_for_the_renewal(db_session, issuer_calls):
    svc.create_certificate(
        db_session,
        CertificateCreate(
            domain="d2.example.com", type="letsencrypt", challenge="dns-01", use_staging=True
        ),
    )

    row = db_session.query(Certificate).filter_by(domain="d2.example.com").one()
    assert row.acme_challenge == "dns-01"
    assert row.acme_staging is True


def test_an_unknown_challenge_is_refused_by_the_schema():
    """A typo must be a 422, not an issuance attempt that fails at the CA."""
    with pytest.raises(ValueError):
        CertificateCreate(domain="x.example.com", type="letsencrypt", challenge="dns-02")


def test_a_selfsigned_certificate_records_no_challenge(db_session):
    """Nothing about ACME applies to it, and a stored 'http-01' would read as if it did."""
    svc.create_certificate(db_session, CertificateCreate(domain="ss.example.com"))

    row = db_session.query(Certificate).filter_by(domain="ss.example.com").one()
    assert row.acme_challenge is None
