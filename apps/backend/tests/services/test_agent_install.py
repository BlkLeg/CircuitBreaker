import http.server
import os
import re
import shlex
import shutil
import ssl
import subprocess
import threading

import pytest

from app.services import agent_install
from app.services.certificate_service import generate_selfsigned


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


def test_render_install_script_is_valid_sh_syntax(tmp_path):
    """Checked with the interpreter the script's own shebang names.

    The script is `#!/bin/sh`; checking it with `bash -n` tested a shell it
    never runs under. `dash` is preferred when the host has it, because that is
    what `/bin/sh` is on the Debian and Ubuntu targets and it rejects bashisms
    bash accepts. Where it is absent — this developer host symlinks /bin/sh to
    bash — the check is only as strict as the local /bin/sh, so treat a pass
    here as necessary rather than sufficient; CI's image is the strict one.

    The template is Python `str.format`, so a literal brace that loses its
    doubling also lands here.
    """
    import shutil
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    script_path = tmp_path / "install-agent.sh"
    script_path.write_text(script)

    shell = shutil.which("dash") or "/bin/sh"
    result = subprocess.run([shell, "-n", str(script_path)], capture_output=True, text=True)
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


def test_script_preflights_the_server_before_touching_the_machine():
    """A wrong address must fail at step one naming the address, not three
    steps later inside a binary download."""
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="de" * 32,
        tls_pin="pin",
        manifest={"1.0.0": {"linux-amd64": "a" * 64}},
    )
    preflight_at = script.index("/api/v1/health")
    useradd_at = script.index("useradd")
    assert preflight_at < useradd_at, "preflight must run before the machine is modified"
    assert "Cannot reach" in script


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


# ── The binary download is verified, not just fetched ────────────────────────
# build_install_command hands out `curl -fsSLk` for the *script* under
# self-signed TLS, but the script's own binary download went out as plain
# `curl -fsSL` against that same self-signed certificate -- so on the default
# deployment it failed verification outright (curl exit 60), and the obvious
# repair (`-k`) would have made it succeed while verifying nothing. The script
# already carries the SPKI pin, and curl enforces --pinnedpubkey even when
# --insecure is in force, so both fetches pin instead.
#
# The release gate never caught this because it reads the script's *text*; the
# sh-level test below actually runs the fetch.

_SELF_SIGNED = dict(
    server_url="https://cb.example.com",
    server_static_pk_hex="ab" * 32,
    tls_pin="c" * 44,
)


def test_binary_download_is_pinned_when_the_server_is_self_signed():
    script = agent_install.render_install_script(
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}}, **_SELF_SIGNED
    )
    assert '--pinnedpubkey "sha256//${CB_TLS_PIN}"' in script, (
        "the install script downloads the agent binary from a self-signed origin "
        "without pinning it -- the fetch either fails verification outright or, "
        "with -k, accepts any certificate at all"
    )
    assert 'curl -fsSL "$CB_BINARY_URL"' not in script, (
        "the binary download still calls curl directly, bypassing the pinned fetch helper"
    )


def test_install_command_pins_the_script_fetch_for_self_signed(db_session, app_cfg, monkeypatch):
    """`-k` on the copied command made `sha256sum -c` the only thing standing
    between the operator and a MITM'd installer. Pin it too, so the digest is a
    second check rather than the sole one."""
    from app.services.certificate_service import generate_selfsigned

    cert_pem, _, _ = generate_selfsigned("cb.home")
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: cert_pem)
    pin = agent_install._spki_pin(cert_pem)

    resp = agent_install.build_install_command(db_session, "https://cb.home")

    assert resp.tls_mode == "self_signed"
    assert f'--pinnedpubkey "sha256//{pin}"' in resp.command
    assert "sha256sum -c" in resp.command  # still there, now as the second check


def test_install_command_does_not_pin_a_publicly_trusted_cert(db_session, app_cfg):
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

    assert "--pinnedpubkey" not in resp.command
    assert "-k" not in resp.command.split()


def test_installer_refuses_to_run_on_a_curl_too_old_to_pin():
    """--pinnedpubkey landed in curl 7.39. Failing closed with a sentence the
    operator can act on beats aborting on `option --pinnedpubkey: is unknown`
    halfway through an install."""
    script = agent_install.render_install_script(
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}}, **_SELF_SIGNED
    )
    assert "7.39" in script
    assert 'curl --pinnedpubkey "sha256//" --version' in script


# ── ...and the fetch actually runs ───────────────────────────────────────────
# Every assertion above reads the script's text, which is exactly the blind
# spot that let the unverified download ship: `test_agent_release_gate.py`
# reads the text too, and `_write_agent_toml` stands in for the heredoc rather
# than executing it. This one runs the script's own fetch helper against a real
# self-signed origin, so it fails if the flags are right but the behavior is
# not.

_FETCH_HELPER = re.compile(r"^cb_curl\(\) \{.*?^\}", re.MULTILINE | re.DOTALL)


def _run_fetch(tmp_path, script: str, pin: str, url: str):
    """Execute just the script's fetch helper, with CB_TLS_PIN bound to `pin`."""
    helper = _FETCH_HELPER.search(script)
    assert helper, "install script no longer defines a cb_curl fetch helper"
    driver = tmp_path / "fetch.sh"
    driver.write_text(
        f'set -eu\nCB_TLS_PIN="{pin}"\n{helper.group(0)}\ncb_curl "{url}" -o "{tmp_path}/out"\n'
    )
    return subprocess.run(["sh", str(driver)], capture_output=True, text=True)


@pytest.fixture
def self_signed_origin(tmp_path):
    """A real HTTPS server on a self-signed cert, plus that cert's SPKI pin."""
    cert_pem, key_pem, _ = generate_selfsigned("cb.test")
    (tmp_path / "t.crt").write_text(cert_pem)
    (tmp_path / "t.key").write_text(key_pem)
    root = tmp_path / "srv"
    root.mkdir()
    (root / "cb-agent").write_bytes(b"ELF-ish payload")

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class _QuietServer(http.server.HTTPServer):
        # A client that rejects the certificate aborts mid-handshake, which
        # socketserver reports by printing a traceback. That is the expected
        # outcome of the pin-mismatch test, so it is noise, not a failure.
        def handle_error(self, request, client_address):
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "t.crt", tmp_path / "t.key")
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield (
            f"https://127.0.0.1:{server.server_address[1]}/cb-agent",
            agent_install._spki_pin(cert_pem),
        )
    finally:
        server.shutdown()


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")
def test_the_scripts_fetch_succeeds_against_the_certificate_it_pinned(tmp_path, self_signed_origin):
    url, pin = self_signed_origin
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin=pin,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )

    result = _run_fetch(tmp_path, script, pin, url)

    assert result.returncode == 0, (
        "the install script cannot download its own binary from a self-signed "
        f"server -- the default deployment: {result.stderr}"
    )
    assert (tmp_path / "out").read_bytes() == b"ELF-ish payload"


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")
def test_the_scripts_fetch_refuses_a_certificate_that_does_not_match_the_pin(
    tmp_path, self_signed_origin
):
    """The half `-k` alone would have thrown away. A MITM presenting its own
    certificate is exactly what the pin is for, so this must not download."""
    url, pin = self_signed_origin
    other_pem, _, _ = generate_selfsigned("attacker.invalid")
    wrong_pin = agent_install._spki_pin(other_pem)
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin=wrong_pin,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )

    result = _run_fetch(tmp_path, script, wrong_pin, url)

    assert result.returncode != 0, "a certificate that does not match the pin was accepted"
    assert not (tmp_path / "out").exists()


@pytest.mark.skipif(shutil.which("curl") is None, reason="curl not installed")
def test_the_scripts_fetch_still_rejects_a_self_signed_cert_when_there_is_no_pin(
    tmp_path, self_signed_origin
):
    """An empty pin means the operator has a publicly trusted certificate. The
    helper must not quietly relax verification for that case -- otherwise the
    fix would hand every `public` install the trust posture of `-k`."""
    url, _ = self_signed_origin
    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="",
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )

    result = _run_fetch(tmp_path, script, "", url)

    assert result.returncode != 0
    assert not (tmp_path / "out").exists()


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


# ── Unprivileged ICMP ────────────────────────────────────────────────────────
#
# The agent's ICMP prober opens datagram ICMP (`icmp.ListenPacket("udp4", ...)`)
# and holds no CAP_NET_RAW, so it can only send an echo request when the
# cb-agent group falls inside net.ipv4.ping_group_range. The installer used to
# check only whether *a* line for that sysctl existed in /etc/sysctl.conf, and
# skip if one did — so a host with a narrower range already set (the kernel
# default `1 0` disables the feature entirely) silently got an agent whose ICMP
# probes could never succeed.


def _run_icmp_block(tmp_path, *, current_range: str, gid: str = "997"):
    """Execute the installer's ICMP snippet against stub sysctl/getent.

    The snippet is shell inside a Python template, so this runs the real thing
    rather than asserting on its source: stubs on PATH stand in for the kernel
    and the passwd database, and the resulting sysctl.conf is the assertion.
    """
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin="c" * 44,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    start = script.index("configure_unprivileged_icmp()")
    end = script.index("\n}\n", start) + len("\n}\n")
    snippet = script[start:end]

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    applied = tmp_path / "applied"
    (bin_dir / "sysctl").write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "-n" ]; then echo "{current_range}"; exit 0; fi\n'
        f'echo applied >> "{applied}"\n'
        "exit 0\n"
    )
    (bin_dir / "getent").write_text(f'#!/bin/sh\necho "cb-agent:x:{gid}:"\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)

    conf = tmp_path / "sysctl.conf"
    conf.write_text("# existing host settings\n")
    runner = tmp_path / "run.sh"
    runner.write_text(
        f"#!/bin/sh\nset -eu\nSYSCTL_CONF='{conf}'\n{snippet}\nconfigure_unprivileged_icmp\n"
    )
    runner.chmod(0o755)

    result = subprocess.run(
        ["/bin/sh", str(runner)],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    return conf.read_text(), applied.exists()


def test_icmp_range_is_widened_when_the_host_disables_ping_sockets(tmp_path):
    """`1 0` is the kernel default and means "no group may": it must be fixed."""
    conf, applied = _run_icmp_block(tmp_path, current_range="1\t0", gid="997")
    assert "net.ipv4.ping_group_range" in conf, conf
    assert applied, "the new range was written but never applied"


def test_icmp_range_is_widened_when_an_existing_range_excludes_the_agent(tmp_path):
    """A pre-existing narrow line used to make the installer skip entirely."""
    conf, applied = _run_icmp_block(tmp_path, current_range="0\t100", gid="997")
    line = [ln for ln in conf.splitlines() if ln.startswith("net.ipv4.ping_group_range")]
    assert line, conf
    low, high = line[-1].split("=")[1].split()
    assert int(low) <= 997 <= int(high), line
    assert applied


def test_icmp_range_is_left_alone_when_it_already_covers_the_agent(tmp_path):
    """Not gratuitously rewriting an operator's own working configuration."""
    conf, applied = _run_icmp_block(tmp_path, current_range="0\t2147483647", gid="997")
    assert "net.ipv4.ping_group_range" not in conf, conf
    assert not applied


def test_icmp_widening_keeps_groups_the_host_already_allowed(tmp_path):
    """Widening is a union, never a replacement — other users keep their ping."""
    conf, _ = _run_icmp_block(tmp_path, current_range="500\t600", gid="997")
    line = [ln for ln in conf.splitlines() if ln.startswith("net.ipv4.ping_group_range")][-1]
    low, high = line.split("=")[1].split()
    assert int(low) <= 500 and int(high) >= 997, line


def _run_preflight(tmp_path, *, reachable: bool, tls_pin: str = "c" * 44):
    """Execute the installer up to and including the user-creation step.

    Runs the real script prefix — the assignments, the curl-version guard,
    `cb_curl`, the reachability preflight and the `useradd` block — against a
    stub curl, rather than asserting on its source. Returns
    `(returncode, stderr, curl_argv, user_created)`.

    `user_created` is the assertion that matters. The preflight exists so that
    a wrong `CB_SERVER_URL` "costs nothing" (design §7): it must fail before
    the script has touched the host. A stub `useradd` that records being called
    is the only thing that can prove that, and asserting on the script's text
    cannot.
    """
    import subprocess

    script = agent_install.render_install_script(
        server_url="https://cb.example.com",
        server_static_pk_hex="ab" * 32,
        tls_pin=tls_pin,
        manifest={"0.1.0": {"linux-amd64": "deadbeef"}},
    )
    prefix = script[: script.index('ARCH="$(uname -m)"')]

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "curl-argv"
    created = tmp_path / "useradd-ran"
    # `--version` must always succeed: it is the curl-too-old guard ahead of
    # the preflight, not a fetch. Every other invocation is the preflight's.
    (bin_dir / "curl").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = "--version" ] && exit 0; done\n'
        f'printf \'%s\\n\' "$@" >> "{argv_log}"\n'
        f"exit {0 if reachable else 7}\n"
    )
    # No cb-agent user on this host, so the script reaches useradd.
    (bin_dir / "id").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "useradd").write_text(f'#!/bin/sh\necho ran > "{created}"\nexit 0\n')
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)

    runner = tmp_path / "run.sh"
    runner.write_text(prefix)
    runner.chmod(0o755)

    result = subprocess.run(
        ["/bin/sh", str(runner)],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    argv = argv_log.read_text().splitlines() if argv_log.exists() else []
    return result.returncode, result.stderr, argv, created.exists()


def test_an_unreachable_server_fails_before_the_installer_touches_the_host(tmp_path):
    """The wrong-endpoint case, and the whole reason the preflight exists.

    An operator who picks the wrong endpoint gets a precise message and a
    machine in exactly the state it was in beforehand — no cb-agent user, no
    binary, no unit. Without this the agent installs cleanly and then dials an
    unreachable address forever, which surfaces as "the agent never appeared".
    """
    code, stderr, _, user_created = _run_preflight(tmp_path, reachable=False)

    assert code == 1, stderr
    assert "Cannot reach https://cb.example.com from this machine." in stderr
    assert not user_created, "the preflight must fail before creating the cb-agent user"


def test_a_reachable_server_carries_on_into_the_install(tmp_path):
    """The other direction: the preflight must not be a gate that never opens."""
    code, stderr, _, user_created = _run_preflight(tmp_path, reachable=True)

    assert code == 0, stderr
    assert user_created, "a reachable server must let the install proceed"


def test_the_preflight_uses_the_same_tls_trust_the_agent_will(tmp_path):
    """It goes through `cb_curl`, so a self-signed install pins the same SPKI
    the agent's tlsdial checks. A preflight that verified differently would
    pass on a server the agent then refuses — a false green at the one moment
    the operator is watching."""
    _, stderr, argv, _ = _run_preflight(tmp_path, reachable=True)

    assert "--pinnedpubkey" in argv, (argv, stderr)
    assert f"sha256//{'c' * 44}" in argv, argv
    assert "https://cb.example.com/api/v1/health" in argv, argv


def test_a_publicly_trusted_install_pins_nothing_in_the_preflight(tmp_path):
    """An empty pin means the system trust store applies; adding --insecure
    there would be a straight downgrade."""
    _, _, argv, _ = _run_preflight(tmp_path, reachable=True, tls_pin="")

    assert "--pinnedpubkey" not in argv, argv
    assert "--insecure" not in argv, argv


@pytest.mark.asyncio
async def test_install_command_uses_the_selected_endpoint_not_the_browsed_host(
    client, auth_headers, db_session, letsencrypt_certificate
):
    """The whole point: the address an agent dials is not the address you browsed.

    `letsencrypt_certificate` sidesteps the unrelated TLS-pin requirement
    (`_tls_mode_and_pin` fails closed with no cert anywhere) so this test's
    only assertion is about which server_url got rendered.
    """
    from app.schemas.settings import AppSettingsUpdate
    from app.services import settings_service

    settings_service.update_settings(
        db_session,
        AppSettingsUpdate(
            agent_endpoints=[{"id": "pub1", "label": "Public", "url": "https://cb.example.com"}]
        ),
    )
    db_session.commit()

    resp = await client.get("/api/v1/agents/install-command?endpoint=pub1", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert "https://cb.example.com" in resp.json()["command"]


@pytest.mark.asyncio
async def test_unknown_endpoint_id_is_refused_rather_than_silently_substituted(
    client, auth_headers
):
    """Falling back here would re-create the defect this feature exists to fix."""
    resp = await client.get("/api/v1/agents/install-command?endpoint=nope", headers=auth_headers)
    assert resp.status_code == 404
    assert "nope" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_absent_endpoint_falls_back_to_the_browsed_host(
    client, auth_headers, letsencrypt_certificate
):
    """Existing installs and existing commands keep working untouched.

    `status_code in (200, 503)` was the whole assertion here, which passes
    whether or not the fallback exists at all. Name the address instead: the
    forwarded host is what the operator browsed, and with no endpoint chosen
    it must be the one baked into the command, with no `?endpoint=` on the
    download link for `/install-agent.sh` to resolve.

    `letsencrypt_certificate` supplies the cert `_tls_mode_and_pin` fails
    closed without, so a missing pin cannot turn this into a vacuous 503.
    """
    resp = await client.get(
        "/api/v1/agents/install-command",
        headers={
            **auth_headers,
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "browsed.example.com",
        },
    )

    assert resp.status_code == 200, resp.text
    command = resp.json()["command"]
    assert _download_url(command) == "https://browsed.example.com/install-agent.sh", command


# ── The emitted command must carry the choice, not just honour it ────────────
# Resolving an endpoint server-side is only half the fix. The command the
# operator pastes is what the *target machine* runs, and that machine's curl is
# what `/install-agent.sh` sees. Without `?endpoint=<id>` on that download URL
# the route takes its `endpoint is None` branch and re-derives the address from
# `forwarded_base_url` — the very derivation §1.1 exists to eliminate — so the
# declared endpoint only lands when the proxy chain happens to reproduce it,
# and `script_sha256` (computed over the endpoint variant) no longer matches
# the fallback variant that was actually downloaded.


def _download_url(command: str) -> str:
    """The `/install-agent.sh` URL an emitted install command downloads.

    Split the way a shell would, so a quoted URL and a bare one both resolve
    to the same string.
    """
    for token in shlex.split(command):
        if "/install-agent.sh" in token:
            return token
    raise AssertionError(f"no install-agent.sh download in command: {command!r}")


def test_install_command_carries_the_endpoint_id_under_self_signed_tls(
    db_session, app_cfg, monkeypatch
):
    cert_pem, _, _ = generate_selfsigned("cb.home")
    monkeypatch.setattr(agent_install, "_live_nginx_cert_pem", lambda: cert_pem)

    resp = agent_install.build_install_command(db_session, "https://cb.home", endpoint_id="pub1")

    assert resp.tls_mode == "self_signed"
    assert _download_url(resp.command) == "https://cb.home/install-agent.sh?endpoint=pub1"


def test_install_command_carries_the_endpoint_id_under_public_tls(
    db_session, app_cfg, letsencrypt_certificate
):
    resp = agent_install.build_install_command(
        db_session, "https://cb.example.com", endpoint_id="pub1"
    )

    assert resp.tls_mode == "public"
    assert _download_url(resp.command) == "https://cb.example.com/install-agent.sh?endpoint=pub1"


def test_install_command_without_an_endpoint_has_no_query_string(
    db_session, app_cfg, letsencrypt_certificate
):
    """Byte-identical to what shipped before endpoints existed: an operator who
    configured none must see exactly today's command."""
    resp = agent_install.build_install_command(db_session, "https://cb.example.com")

    assert resp.command == "curl -fsSL https://cb.example.com/install-agent.sh | sudo sh"
