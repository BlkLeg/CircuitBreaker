"""Creating a certificate must never store one type's bytes under another type's name.

INC-07: create_certificate branched on whether a PEM was pasted and never on data.type, so
choosing "Let's Encrypt" without a PEM generated a self-signed certificate and stored it with
type="letsencrypt". The table then rendered it as "Let's Encrypt".
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from app.db.models import Certificate
from app.schemas.certificate import CertificateCreate
from app.services import certificate_service as svc


@pytest.fixture(autouse=True)
def _vault_ready():
    """Load the in-memory vault with the suite's test key."""
    from app.services.credential_vault import get_vault

    get_vault().reinitialize(os.environ["CB_VAULT_KEY"])


def test_selfsigned_generates(db_session):
    cert = svc.create_certificate(
        db_session, CertificateCreate(domain="a.example.com", type="selfsigned")
    )

    assert cert.type == "selfsigned"
    assert "BEGIN CERTIFICATE" in cert.cert_pem


def test_imported_without_a_pem_is_rejected(db_session):
    with pytest.raises(svc.CertificateCreationError):
        svc.create_certificate(
            db_session, CertificateCreate(domain="b.example.com", type="imported")
        )


def test_letsencrypt_without_acme_creates_no_row(db_session, monkeypatch):
    """The direct inversion of the defect: refuse rather than silently self-sign."""

    def _refuse(domain, **kwargs):
        raise svc.CertificateRenewalError("CB_TLS_EMAIL is not set")

    monkeypatch.setattr(svc, "issue_acme_certificate", _refuse, raising=False)

    before = db_session.query(Certificate).count()
    with pytest.raises(svc.CertificateRenewalError):
        svc.create_certificate(
            db_session, CertificateCreate(domain="c.example.com", type="letsencrypt")
        )

    assert db_session.query(Certificate).count() == before


def test_no_path_stores_a_selfsigned_cert_under_another_type(db_session, monkeypatch):
    monkeypatch.setattr(
        svc,
        "issue_acme_certificate",
        lambda domain, **kw: ("-- le cert --", "-- le key --", datetime(2030, 1, 1, tzinfo=UTC)),
        raising=False,
    )

    svc.create_certificate(
        db_session, CertificateCreate(domain="d.example.com", type="letsencrypt")
    )

    row = db_session.query(Certificate).filter_by(domain="d.example.com").one()
    assert row.cert_pem == "-- le cert --"
    assert row.type == "letsencrypt"


def test_pasted_pem_under_type_selfsigned_is_not_imported(db_session):
    """The old branch keyed on "was a PEM pasted", which let a pasted PEM land under any type.

    Type decides; the PEM fields are only read when the type says imported.
    """
    cert = svc.create_certificate(
        db_session,
        CertificateCreate(
            domain="e.example.com",
            type="selfsigned",
            cert_pem="-- pasted cert --",
            key_pem="-- pasted key --",
        ),
    )

    assert cert.cert_pem != "-- pasted cert --"
    assert "BEGIN CERTIFICATE" in cert.cert_pem
