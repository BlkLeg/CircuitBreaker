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


def test_build_install_command_self_signed_includes_hash_verification(db_session, app_cfg):
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
