import os

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
    assert 'ln -sfn "versions/0.5.0/cb-agent" /var/lib/cb-agent/current' in script
    assert "chown -h cb-agent:cb-agent /var/lib/cb-agent/current" in script
    assert "ln -sfn /var/lib/cb-agent/current /usr/local/bin/cb-agent" in script
    # Never installed directly at the top-level path anymore.
    assert 'install -m 0755 "$TMP_BIN" /usr/local/bin/cb-agent' not in script


def test_build_install_command_self_signed_includes_hash_verification(
    db_session, app_cfg, monkeypatch
):
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
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: None)

    # No cert from database (None)
    with pytest.raises(ValueError, match="Cannot obtain TLS pin"):
        agent_install._tls_mode_and_pin(None)


def test_tls_mode_and_pin_raises_for_self_signed_without_pin(monkeypatch, db_session):
    """Fail closed when self-signed cert has no available pin."""
    from datetime import timedelta

    from app.core.time import utcnow
    from app.db.models import Certificate

    # Mock _live_nginx_cert_pem to return None
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: None)

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
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: None)

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


# ── Reading the cert nginx actually serves ───────────────────────────────────
# Every test above mocks _live_nginx_cert_pem, so nothing ever exercised the
# real read against a real file. A native install leaves that file readable
# only by root and the nginx group while the backend runs as `breaker`, so the
# PermissionError was swallowed by `except OSError` and surfaced as "neither
# live nginx cert nor database cert available" — a 500 on Add Agent with no
# clue in the message about what was actually wrong.


def _write_cert(tmp_path, cn="circuitbreaker"):
    from app.services.certificate_service import generate_selfsigned

    cert_pem, _, _ = generate_selfsigned(cn)
    tls_dir = tmp_path / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)
    cert_file = tls_dir / "fullchain.pem"
    cert_file.write_text(cert_pem)
    return cert_file, cert_pem


def test_live_nginx_cert_pem_reads_the_file_the_installer_writes(tmp_path, monkeypatch):
    cert_file, cert_pem = _write_cert(tmp_path)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    assert agent_install._live_nginx_cert_pem() == cert_pem
    mode, pin = agent_install._tls_mode_and_pin(None)
    assert mode == "self_signed"
    assert pin == agent_install._spki_pin(cert_pem)
    assert cert_file.exists()


def test_missing_cert_file_is_not_an_error_by_itself(tmp_path, monkeypatch):
    """No file at all is a legitimate "fall back to the database row" case."""
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    assert agent_install._live_nginx_cert_pem() is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_cert_says_so_instead_of_claiming_none_exists(tmp_path, monkeypatch):
    cert_file, _ = _write_cert(tmp_path)
    cert_file.chmod(0o000)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    with pytest.raises(ValueError) as exc_info:
        agent_install._tls_mode_and_pin(None)

    message = str(exc_info.value)
    assert str(cert_file) in message
    assert "readable" in message.lower() or "permission" in message.lower()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_cert_does_not_silently_pin_a_stale_database_cert(tmp_path, monkeypatch):
    """A DB row need not be what nginx serves; pinning it would break enrollment
    in a way that only shows up as a TLS failure on the agent, far from here."""
    from app.db.models import Certificate
    from app.services.certificate_service import generate_selfsigned

    other_pem, _, _ = generate_selfsigned("something-else.invalid")
    stale = Certificate(domain="something-else.invalid", type="self-signed", cert_pem=other_pem)

    cert_file, _ = _write_cert(tmp_path)
    cert_file.chmod(0o000)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    with pytest.raises(ValueError):
        agent_install._tls_mode_and_pin(stale)


def test_letsencrypt_needs_no_pin_even_with_an_unreadable_file(tmp_path, monkeypatch, db_session):
    """A publicly trusted cert is validated by the OS trust store, so an
    unreadable local file is irrelevant and must not block the install."""
    from app.db.models import Certificate

    cert_file, _ = _write_cert(tmp_path)
    cert_file.chmod(0o000)
    monkeypatch.setenv("CB_DATA_DIR", str(tmp_path))

    mode, pin = agent_install._tls_mode_and_pin(
        Certificate(domain="cb.example.com", type="letsencrypt", cert_pem="")
    )
    assert mode == "public"
    assert pin == ""


# ── The systemd unit the installer writes ────────────────────────────────────
#
# Nothing pinned this template before, which is exactly how the AF_NETLINK
# defect shipped and stayed invisible: the agent e2e suite runs the binary in a
# container with no systemd sandbox around it, and `cb-agent enroll` runs from
# the operator's shell for the same reason. The unit is the only supported way
# to run the daemon, so its sandbox is production behaviour and belongs under
# test like any other.


def _unit_directive(name: str) -> str:
    """The value of one directive in the unit the install script writes."""
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    for line in script.splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"the unit template has no {name} directive:\n{script}")


def test_unit_allows_netlink_so_discovery_and_probing_work():
    """RTM_GETNEIGH and Go's net.Interfaces() are both netlink on Linux.

    Without AF_NETLINK the daemon cannot enumerate its own interfaces, so the
    derived `direct_private` scope arrives empty and every discovery target and
    probe destination is refused `empty_scope` before a packet is sent.
    """
    families = _unit_directive("RestrictAddressFamilies").split()
    assert "AF_NETLINK" in families, families


def test_unit_still_grants_the_families_the_agent_already_needed():
    families = _unit_directive("RestrictAddressFamilies").split()
    for required in ("AF_UNIX", "AF_INET", "AF_INET6"):
        assert required in families, families


def test_unit_does_not_grant_raw_packet_access():
    """AF_NETLINK is a read-only RTM_GETNEIGH dump, not a licence for AF_PACKET."""
    families = _unit_directive("RestrictAddressFamilies").split()
    assert "AF_PACKET" not in families, families


def test_unit_keeps_the_filesystem_sandbox_self_update_depends_on():
    """Self-update writes only under the state dir, which must stay writable."""
    assert _unit_directive("ProtectSystem") == "strict"
    assert _unit_directive("ReadWritePaths") == "/var/lib/cb-agent"
    assert _unit_directive("NoNewPrivileges") == "true"
