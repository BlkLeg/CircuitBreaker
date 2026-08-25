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


def test_activation_writes_both_files_with_safe_modes(db_session, tmp_path, monkeypatch):
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "reloaded via supervisorctl"))
    monkeypatch.setattr(act, "_decrypt_key", lambda pem: "-- plaintext key --")

    cert = _cert(db_session, "a.example.com")
    result = act.activate_certificate(db_session, cert)

    chain = tmp_path / "tls" / "fullchain.pem"
    key = tmp_path / "tls" / "privkey.pem"
    assert chain.read_text() == "-- cert --"
    assert key.read_text() == "-- plaintext key --"
    assert oct(key.stat().st_mode)[-3:] == "600"
    assert result.written is True and result.reloaded is True
    assert cert.is_active is True


def test_activation_deactivates_the_previous_certificate(db_session, tmp_path, monkeypatch):
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "ok"))
    monkeypatch.setattr(act, "_decrypt_key", lambda pem: "k")

    old = _cert(db_session, "old.example.com", active=True)
    new = _cert(db_session, "new.example.com")

    act.activate_certificate(db_session, new)

    assert old.is_active is False
    assert new.is_active is True


def test_a_failed_write_leaves_the_previous_files_intact(db_session, tmp_path, monkeypatch):
    """os.replace is atomic; a crash mid-write must not produce a half-written key."""
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    tls = tmp_path / "tls"
    tls.mkdir(parents=True)
    (tls / "fullchain.pem").write_text("PREVIOUS-CERT")
    (tls / "privkey.pem").write_text("PREVIOUS-KEY")

    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "ok"))

    def _boom(pem):
        raise RuntimeError("vault unavailable")

    monkeypatch.setattr(act, "_decrypt_key", _boom)

    cert = _cert(db_session, "a.example.com")
    with pytest.raises(RuntimeError):
        act.activate_certificate(db_session, cert)

    assert (tls / "fullchain.pem").read_text() == "PREVIOUS-CERT"
    assert (tls / "privkey.pem").read_text() == "PREVIOUS-KEY"


def test_no_reload_mechanism_is_reported_not_claimed(db_session, tmp_path, monkeypatch):
    """The plain image has no nginx. Writing the files is all we can do; say so."""
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(act, "_decrypt_key", lambda pem: "k")
    monkeypatch.setattr(act, "_supervisorctl_available", lambda: False)
    monkeypatch.setattr(act, "_helper_available", lambda: False)

    result = act.activate_certificate(db_session, _cert(db_session, "a.example.com"))

    assert result.written is True
    assert result.reloaded is False
    assert "no TLS server" in result.detail or "reload" in result.detail.lower()
