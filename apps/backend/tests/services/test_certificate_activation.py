"""Certificate activation — INC-22.

`nginx.mono.conf:81` serves /data/tls/fullchain.pem. Nothing in certificate_service.py ever
wrote there, so every certificate the Certificates page managed — self-signed renewals
included — was a database row no TLS listener read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Certificate


def _cert(db: Session, domain: str, *, active: bool = False) -> Certificate:
    cert = Certificate(
        domain=domain,
        type="selfsigned",
        cert_pem="-- cert --",
        key_pem="-- key --",
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        auto_renew=True,
        is_active=active,
    )
    db.add(cert)
    db.flush()
    return cert


def test_certificates_default_to_inactive(db_session):
    cert = _cert(db_session, "a.example.com")

    assert cert.is_active is False


def test_two_active_certificates_are_refused_by_the_database(db_session):
    """Two active certificates is a state where 'what are we serving?' has no answer."""
    _cert(db_session, "a.example.com", active=True)

    with pytest.raises(IntegrityError):
        _cert(db_session, "b.example.com", active=True)
        db_session.flush()


def test_many_inactive_certificates_are_fine(db_session):
    _cert(db_session, "a.example.com")
    _cert(db_session, "b.example.com")
    _cert(db_session, "c.example.com", active=True)

    assert db_session.query(Certificate).filter(Certificate.is_active).count() == 1
