import pytest

from app.services import agent_install


def test_render_install_script_embeds_server_identity():
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef", "linux-arm64": "beadfeed"}},
    )
    assert "https://cb.example.com" in script
    assert "ab" * 32 in script
    assert "c" * 44 in script
    assert "deadbeef" in script
    assert "cb-agent enroll" in script
    assert "systemctl enable --now cb-agent" in script


def test_render_install_script_picks_highest_semver_not_lexicographic():
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={
            "0.2.0": {"linux-amd64": "old-digest"},
            "0.10.0": {"linux-amd64": "new-digest"},
        },
    )
    # 0.10.0 is the highest version even though a plain string sort would
    # rank "0.10.0" before "0.2.0".
    assert "/0.10.0/linux/" in script
    assert "new-digest" in script
    assert "old-digest" not in script


def test_render_install_script_excludes_other_os_digest_for_same_arch():
    """The generated script always installs the linux/${CB_ARCH} binary, so
    a same-arch entry for a different OS (e.g. darwin-amd64 alongside
    linux-amd64) must never leak its digest into the amd64 case — otherwise
    the script could verify the downloaded linux binary against a digest
    computed for an entirely different OS build."""
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={
            "0.1.0": {
                "linux-amd64": "linux-digest",
                "darwin-amd64": "darwin-digest",
            },
        },
    )
    assert "linux-digest" in script
    assert "darwin-digest" not in script


def test_render_install_script_is_valid_bash_syntax(tmp_path):
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    script_path = tmp_path / "install-agent.sh"
    script_path.write_text(script)

    result = subprocess.run(["bash", "-n", str(script_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_render_install_script_creates_versioned_symlink_layout():
    """Bug 1 fix (specs/2026-08-05-cb-agent-self-update-fix-design.md): the
    binary must land in a per-version directory under /var/lib/cb-agent,
    never directly at /usr/local/bin/cb-agent, with both symlinks
    (current -> versions/<v>, /usr/local/bin/cb-agent -> current) created
    and correctly owned — this is what lets the unprivileged cb-agent user
    perform a self-update entirely within permissions it already has.
    """
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.5.0": {"linux-amd64": "deadbeef"}},
    )
    assert 'install -d -m 0755 -o cb-agent -g cb-agent "/var/lib/cb-agent/versions/0.5.0"' in script
    assert '"/var/lib/cb-agent/versions/0.5.0/cb-agent"' in script
    assert 'ln -sfn "versions/0.5.0" /var/lib/cb-agent/current' in script
    assert "chown -h cb-agent:cb-agent /var/lib/cb-agent/current" in script
    assert "ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent" in script
    # Never installed directly at the top-level path anymore.
    assert 'install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent' not in script


def test_build_install_command_self_signed_includes_hash_verification(db_session, app_cfg, monkeypatch):
    from app.services.certificate_service import generate_selfsigned

    # Generate a valid self-signed certificate
    valid_cert_pem, _, _ = generate_selfsigned("cb.home")

    # Mock _live_nginx_cert_pem to return the generated cert
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: valid_cert_pem)

    resp = agent_install.build_install_command(db_session, "https://cb.home")
    assert resp.tls_mode == "self_signed"
    assert "sha256sum -c" in resp.command
    assert resp.script_sha256 in resp.command


def test_build_install_command_public_tls_omits_hash_verification(db_session, app_cfg):
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import Certificate

    db_session.add(
        Certificate(
            domain="cb.example.com",
            type="letsencrypt",
            cert_pem="-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
            key_pem="-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
            expires_at=utcnow() + timedelta(days=60),
        )
    )
    db_session.flush()

    resp = agent_install.build_install_command(db_session, "https://cb.example.com")
    assert resp.tls_mode == "public"
    assert "sha256sum -c" not in resp.command


def test_tls_mode_and_pin_raises_when_no_cert_and_no_live_cert(monkeypatch):
    """Fail closed when cert/pin cannot be obtained for self-signed."""
    # Mock _live_nginx_cert_pem to return None (simulating cert file not available)
    monkeypatch.setattr(
        agent_install, "_live_nginx_cert_pem", lambda: None
    )

    # No cert from database (None)
    with pytest.raises(ValueError, match="Cannot obtain TLS pin"):
        agent_install._tls_mode_and_pin(None)


def test_tls_mode_and_pin_raises_for_self_signed_without_pin(monkeypatch, db_session):
    """Fail closed when self-signed cert has no available pin."""
    from app.db.models import Certificate
    from app.core.time import utcnow
    from datetime import timedelta

    # Mock _live_nginx_cert_pem to return None
    monkeypatch.setattr(
        agent_install, "_live_nginx_cert_pem", lambda: None
    )

    # Add a self-signed certificate with invalid/incomplete PEM
    # (that will cause _spki_pin to fail)
    invalid_cert = Certificate(
        domain="cb.example.com",
        type="self_signed",
        cert_pem="invalid-pem-data",
        key_pem="invalid-key",
        expires_at=utcnow() + timedelta(days=30),
    )

    with pytest.raises((ValueError, Exception)):
        agent_install._tls_mode_and_pin(invalid_cert)


def test_build_install_command_fails_closed_without_pin(monkeypatch, db_session):
    """Install command generation fails when TLS pin cannot be obtained."""
    # Mock _live_nginx_cert_pem to return None
    monkeypatch.setattr(
        agent_install, "_live_nginx_cert_pem", lambda: None
    )

    # No certificate in database
    with pytest.raises(ValueError, match="Cannot obtain TLS pin"):
        agent_install.build_install_command(db_session, "https://cb.example.com")


# ── Task 28: install scripts reflect the successor key after activation ────


def _add_letsencrypt_cert(db_session) -> None:
    """A `letsencrypt`-typed cert makes `_tls_mode_and_pin` return an empty,
    deterministic pin (`tls_mode="public"`) — these tests only care about
    which server public key `build_install_command` embeds, not TLS pinning,
    so this sidesteps `test_build_install_command_fails_closed_without_pin`'s
    fail-closed path entirely."""
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import Certificate

    db_session.add(
        Certificate(
            domain="cb.example.com",
            type="letsencrypt",
            cert_pem="-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----",
            key_pem="-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
            expires_at=utcnow() + timedelta(days=60),
        )
    )
    db_session.flush()


def test_build_install_command_uses_current_key_with_no_rotation_in_progress(db_session, app_cfg):
    import hashlib

    from app.core.agent_crypto import get_server_static_keypair

    _, current_pub = get_server_static_keypair()
    _add_letsencrypt_cert(db_session)

    resp = agent_install.build_install_command(db_session, "https://cb.example.com")

    expected_script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex=current_pub.hex(),
        tls_pin="",
        manifest=agent_install.agent_update.load_manifest(),
    )
    assert resp.script_sha256 == hashlib.sha256(expected_script.encode()).hexdigest()


def test_build_install_command_prefers_successor_key_once_rotation_starts(db_session, app_cfg):
    import hashlib

    from app.core.agent_crypto import get_server_static_keypair, start_server_key_rotation

    get_server_static_keypair()  # ensure the current key exists before rotating
    _add_letsencrypt_cert(db_session)
    state = start_server_key_rotation(db_session)
    assert state is not None and state.successor_pub is not None

    resp = agent_install.build_install_command(db_session, "https://cb.example.com")

    expected_script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex=state.successor_pub.hex(),
        tls_pin="",
        manifest=agent_install.agent_update.load_manifest(),
    )
    # build_install_command's own script hash must match a script rendered
    # with the *successor* key, not the current one — the successor key is
    # the one this fresh install stays valid under after the current key is
    # retired at the end of the overlap window.
    assert resp.script_sha256 == hashlib.sha256(expected_script.encode()).hexdigest()
