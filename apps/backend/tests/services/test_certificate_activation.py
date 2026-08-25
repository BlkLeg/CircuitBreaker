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
    monkeypatch.setattr(act, "_reload_tls", lambda: (True, "reloaded"))
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
    monkeypatch.setenv("CB_NGINX_PID_FILE", str(tmp_path / "no-nginx.pid"))
    monkeypatch.setattr(act, "_helper_available", lambda: False)

    result = act.activate_certificate(db_session, _cert(db_session, "a.example.com"))

    assert result.written is True
    assert result.reloaded is False
    assert "no TLS server" in result.detail or "reload" in result.detail.lower()


# ------------------------------------------------------------------------------
# The reload itself. These exercise `_reload_tls` for real — a real process, a real
# signal, a real permission boundary — rather than monkeypatching the function out.
#
# The seam they protect: activation used to shell out to `supervisorctl signal HUP
# nginx`, but supervisorctl talks to supervisord's control socket, and in the mono
# image that socket is root-owned 0700 (docker/supervisord.mono.conf) while
# `[program:backend-api]` runs as `breaker`. Every call returned EACCES, so every
# activation reported reloaded=false and served the old certificate. nginx's master
# runs as `breaker` too, so signalling its pid directly needs no privilege at all.
# ------------------------------------------------------------------------------

_CATCHER = """
import pathlib, signal, sys, time

marker = pathlib.Path(sys.argv[1])
signal.signal(signal.SIGHUP, lambda *a: (marker.write_text("hup"), sys.exit(0)))
pathlib.Path(sys.argv[2]).write_text("ready")
time.sleep(30)
"""


def _spawn_sighup_catcher(tmp_path):
    """A real process that records the SIGHUP it receives, standing in for nginx."""
    import subprocess
    import sys
    import time

    marker = tmp_path / "hup-received"
    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, "-c", _CATCHER, str(marker), str(ready)])
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError("stand-in nginx exited before installing its handler")
        time.sleep(0.01)
    assert ready.exists(), "stand-in nginx never became ready"
    return proc, marker


def test_reload_sighups_the_real_nginx_process(tmp_path, monkeypatch):
    """nginx reloads on SIGHUP. Send it to the pid in nginx's pidfile, and check it lands."""
    import time

    from app.services import certificate_activation as act

    proc, marker = _spawn_sighup_catcher(tmp_path)
    try:
        pid_file = tmp_path / "nginx.pid"
        pid_file.write_text(f"{proc.pid}\n")
        monkeypatch.setenv("CB_NGINX_PID_FILE", str(pid_file))

        reloaded, detail = act._reload_tls()

        assert reloaded is True, detail
        assert proc.wait(timeout=10) == 0
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.read_text() == "hup"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_reload_reports_a_pidfile_naming_a_dead_process(tmp_path, monkeypatch):
    """A stale pidfile must not be read as a successful reload."""
    from app.services import certificate_activation as act

    proc, _ = _spawn_sighup_catcher(tmp_path)
    proc.kill()
    proc.wait(timeout=10)

    pid_file = tmp_path / "nginx.pid"
    pid_file.write_text(f"{proc.pid}\n")
    monkeypatch.setenv("CB_NGINX_PID_FILE", str(pid_file))

    reloaded, detail = act._reload_tls()

    assert reloaded is False
    assert str(proc.pid) in detail


def test_reload_reports_a_process_it_is_not_permitted_to_signal(tmp_path, monkeypatch):
    """The real permission boundary: a pid owned by another user.

    This is the failure the supervisorctl implementation hit on every call and reported
    only in a truncated stderr string. It must come back as reloaded=False with the pid
    named, never as a claimed reload.
    """
    import os

    from app.services import certificate_activation as act

    try:
        init_uid = os.stat("/proc/1").st_uid
    except OSError:  # pragma: no cover - non-Linux
        pytest.skip("no /proc/1 to borrow as a process owned by another user")
    if init_uid == os.geteuid():
        pytest.skip("pid 1 is ours; no unprivileged signal boundary available here")

    pid_file = tmp_path / "nginx.pid"
    pid_file.write_text("1\n")
    monkeypatch.setenv("CB_NGINX_PID_FILE", str(pid_file))

    reloaded, detail = act._reload_tls()

    assert reloaded is False
    assert "permit" in detail.lower() or "permission" in detail.lower()


def test_reload_falls_through_to_the_helper_when_there_is_no_nginx(tmp_path, monkeypatch):
    """Native install: no nginx pidfile in the container sense; cb-helperd reloads it."""
    from app.services import certificate_activation as act

    monkeypatch.setenv("CB_NGINX_PID_FILE", str(tmp_path / "absent.pid"))
    monkeypatch.setattr(act, "_helper_available", lambda: True)
    calls = []
    monkeypatch.setattr(
        "app.services.helper_client.call_helper",
        lambda action, params: calls.append(action),
    )

    reloaded, detail = act._reload_tls()

    assert reloaded is True, detail
    assert calls == ["reload_nginx"]


def test_reload_ignores_an_unreadable_pidfile_and_says_so(tmp_path, monkeypatch):
    """Garbage in the pidfile is 'we do not know where nginx is', not a reload."""
    from app.services import certificate_activation as act

    pid_file = tmp_path / "nginx.pid"
    pid_file.write_text("not-a-pid\n")
    monkeypatch.setenv("CB_NGINX_PID_FILE", str(pid_file))
    monkeypatch.setattr(act, "_helper_available", lambda: False)

    reloaded, detail = act._reload_tls()

    assert reloaded is False
    assert "no TLS server" in detail
