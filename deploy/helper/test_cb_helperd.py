import json
import os
import socket
import struct
import tempfile

import cb_helperd


def _pair():
    return socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)


def test_send_and_recv_message_roundtrip():
    a, b = _pair()
    try:
        cb_helperd.send_message(a, {"action": "get_host_readiness", "params": {}})
        msg = cb_helperd.recv_message(b)
        assert msg == {"action": "get_host_readiness", "params": {}}
    finally:
        a.close()
        b.close()


def test_recv_message_raises_on_closed_connection():
    a, b = _pair()
    a.close()
    try:
        try:
            cb_helperd.recv_message(b)
            assert False, "expected ConnectionError"
        except ConnectionError:
            pass
    finally:
        b.close()


def test_peer_uid_matches_own_process():
    a, b = _pair()
    try:
        assert cb_helperd.peer_uid(a) == os.getuid()
        assert cb_helperd.peer_uid(b) == os.getuid()
    finally:
        a.close()
        b.close()


def test_read_authorized_uid_parses_conf_file():
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
        fh.write("# comment\nAUTHORIZED_UID=1000\nCOMPOSE_DIR=/opt/circuitbreaker\n")
        path = fh.name
    try:
        assert cb_helperd.read_authorized_uid(path) == 1000
    finally:
        os.remove(path)


def test_read_conf_parses_all_keys():
    with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as fh:
        fh.write("AUTHORIZED_UID=1000\nCOMPOSE_DIR=/opt/circuitbreaker\n\n# comment\n")
        path = fh.name
    try:
        conf = cb_helperd.read_conf(path)
        assert conf == {"AUTHORIZED_UID": "1000", "COMPOSE_DIR": "/opt/circuitbreaker"}
    finally:
        os.remove(path)


def test_dispatch_rejects_unknown_action():
    result = cb_helperd.dispatch("delete_everything", {})
    assert result == {"ok": False, "error": "unknown action: 'delete_everything'"}


def test_dispatch_routes_to_registered_handler(monkeypatch):
    monkeypatch.setitem(cb_helperd._ACTIONS, "get_host_readiness", lambda params: {"probe": True})
    result = cb_helperd.dispatch("get_host_readiness", {})
    assert result == {"ok": True, "data": {"probe": True}}


def test_dispatch_wraps_handler_exception():
    def _boom(params):
        raise RuntimeError("nope")

    import cb_helperd as m

    old = m._ACTIONS.get("ensure_nmap")
    m._ACTIONS["ensure_nmap"] = _boom
    try:
        result = m.dispatch("ensure_nmap", {})
        assert result == {"ok": False, "error": "nope"}
    finally:
        if old is not None:
            m._ACTIONS["ensure_nmap"] = old


def test_handle_connection_rejects_wrong_uid():
    a, b = _pair()
    try:
        cb_helperd.handle_connection(b, authorized_uid=os.getuid() + 12345)
        cb_helperd.send_message  # no-op reference to keep import used
        a.settimeout(2)
        response = cb_helperd.recv_message(a)
        assert response == {"ok": False, "error": "unauthorized"}
    finally:
        a.close()


def test_handle_connection_dispatches_for_authorized_uid(monkeypatch):
    monkeypatch.setitem(cb_helperd._ACTIONS, "get_host_readiness", lambda params: {"ok_probe": True})
    a, b = _pair()
    try:
        cb_helperd.send_message(a, {"action": "get_host_readiness", "params": {}})
        cb_helperd.handle_connection(b, authorized_uid=os.getuid())
        response = cb_helperd.recv_message(a)
        assert response == {"ok": True, "data": {"ok_probe": True}}
    finally:
        a.close()


from unittest.mock import patch, MagicMock


def test_detect_pkg_manager_prefers_first_found():
    with patch("shutil.which", side_effect=lambda name: "/usr/bin/apt-get" if name == "apt-get" else None):
        assert cb_helperd.detect_pkg_manager() == "apt-get"


def test_detect_pkg_manager_returns_none_when_none_found():
    with patch("shutil.which", return_value=None):
        assert cb_helperd.detect_pkg_manager() is None


def test_action_ensure_nmap_already_present():
    with patch("shutil.which", return_value="/usr/bin/nmap"):
        result = cb_helperd.action_ensure_nmap({})
        assert result == {"already_present": True}


def test_action_ensure_nmap_installs_when_missing():
    which_calls = {"n": 0}

    def _which(name):
        if name == "nmap":
            which_calls["n"] += 1
            return None if which_calls["n"] == 1 else "/usr/bin/nmap"
        if name == "apt-get":
            return "/usr/bin/apt-get"
        return None

    with (
        patch("shutil.which", side_effect=_which),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as run,
    ):
        result = cb_helperd.action_ensure_nmap({})
        assert result == {"already_present": False, "package_manager": "apt-get"}
        run.assert_called_once_with(
            ["apt-get", "install", "-y", "-q", "nmap"], capture_output=True, text=True, timeout=120
        )


def test_action_ensure_nmap_raises_when_no_pkg_manager():
    with patch("shutil.which", return_value=None):
        try:
            cb_helperd.action_ensure_nmap({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "package manager" in str(exc)


def test_action_ensure_nmap_raises_on_install_failure():
    def _which(name):
        return "/usr/bin/apt-get" if name == "apt-get" else None

    with (
        patch("shutil.which", side_effect=_which),
        patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="no network")),
    ):
        try:
            cb_helperd.action_ensure_nmap({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "no network" in str(exc)


def test_action_grant_nmap_caps_success():
    with (
        patch("shutil.which", return_value="/usr/bin/nmap"),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")) as run,
    ):
        result = cb_helperd.action_grant_nmap_caps({})
        assert result == {"nmap_path": "/usr/bin/nmap"}
        run.assert_called_once_with(
            ["setcap", "cap_net_raw+eip", "/usr/bin/nmap"], capture_output=True, text=True, timeout=10
        )


def test_action_grant_nmap_caps_raises_when_nmap_missing():
    with patch("shutil.which", return_value=None):
        try:
            cb_helperd.action_grant_nmap_caps({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "run ensure_nmap first" in str(exc)


def test_action_get_host_readiness_all_present():
    def _which(name):
        return {"nmap": "/usr/bin/nmap", "docker": "/usr/bin/docker"}.get(name)

    with (
        patch("shutil.which", side_effect=_which),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="cap_net_raw+eip")),
    ):
        result = cb_helperd.action_get_host_readiness({})
        assert result == {"nmap_present": True, "nmap_capped": True, "docker_available": True}


def test_action_get_host_readiness_nothing_present():
    with patch("shutil.which", return_value=None):
        result = cb_helperd.action_get_host_readiness({})
        assert result == {"nmap_present": False, "nmap_capped": False, "docker_available": False}


import os as _os


def test_enable_lan_discovery_noop_on_bare_metal(tmp_path):
    conf = tmp_path / "helper.conf"
    conf.write_text("AUTHORIZED_UID=1000\n")
    with patch("cb_helperd.CONF_PATH", str(conf)):
        result = cb_helperd.action_enable_lan_discovery({})
        assert result["applied"] is False
        assert "bare-metal" in result["reason"]


def test_enable_lan_discovery_writes_override_and_recreates(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text("services:\n  circuitbreaker: {}\n")
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")

    calls = []

    def _run(cmd, **kwargs):
        calls.append((cmd, kwargs.get("cwd")))
        return MagicMock(returncode=0, stdout="config-ok", stderr="")

    with (
        patch("cb_helperd.CONF_PATH", str(conf)),
        patch("subprocess.run", side_effect=_run),
        patch("cb_helperd._health_check", return_value=True),
    ):
        result = cb_helperd.action_enable_lan_discovery({})
    assert result["applied"] is True
    override_path = compose_dir / cb_helperd.OVERRIDE_FILENAME
    assert override_path.exists()
    assert "network_mode: host" in override_path.read_text()
    up_calls = [c for c in calls if "up" in c[0]]
    assert len(up_calls) == 1
    assert str(compose_dir) == up_calls[0][1]


def test_enable_lan_discovery_rolls_back_on_compose_failure(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text("services:\n  circuitbreaker: {}\n")
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")

    def _run(cmd, **kwargs):
        if "config" in cmd:
            return MagicMock(returncode=0, stdout="snapshot", stderr="")
        return MagicMock(returncode=1, stdout="", stderr="daemon busy")

    with (
        patch("cb_helperd.CONF_PATH", str(conf)),
        patch("subprocess.run", side_effect=_run),
    ):
        try:
            cb_helperd.action_enable_lan_discovery({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "daemon busy" in str(exc)
    override_path = compose_dir / cb_helperd.OVERRIDE_FILENAME
    assert not override_path.exists()  # rollback removed it


def test_enable_lan_discovery_rolls_back_on_failed_health_check(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text("services:\n  circuitbreaker: {}\n")
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")

    with (
        patch("cb_helperd.CONF_PATH", str(conf)),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")),
        patch("cb_helperd._health_check", return_value=False),
    ):
        try:
            cb_helperd.action_enable_lan_discovery({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "health check" in str(exc)
    override_path = compose_dir / cb_helperd.OVERRIDE_FILENAME
    assert not override_path.exists()


def test_enable_lan_discovery_raises_when_base_compose_missing(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")
    with patch("cb_helperd.CONF_PATH", str(conf)):
        try:
            cb_helperd.action_enable_lan_discovery({})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "base compose file not found" in str(exc)


def test_disable_lan_discovery_noop_on_bare_metal(tmp_path):
    conf = tmp_path / "helper.conf"
    conf.write_text("AUTHORIZED_UID=1000\n")
    with patch("cb_helperd.CONF_PATH", str(conf)):
        result = cb_helperd.action_disable_lan_discovery({})
        assert result["applied"] is False


def test_disable_lan_discovery_noop_when_override_absent(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")
    with patch("cb_helperd.CONF_PATH", str(conf)):
        result = cb_helperd.action_disable_lan_discovery({})
        assert result == {"applied": True, "reason": "override already absent"}


def test_disable_lan_discovery_removes_override_and_recreates(tmp_path):
    compose_dir = tmp_path / "install"
    compose_dir.mkdir()
    (compose_dir / "docker-compose.yml").write_text("services:\n  circuitbreaker: {}\n")
    override = compose_dir / "docker-compose.lan-discovery.yml"
    override.write_text("services:\n  circuitbreaker:\n    network_mode: host\n")
    conf = tmp_path / "helper.conf"
    conf.write_text(f"AUTHORIZED_UID=1000\nCOMPOSE_DIR={compose_dir}\n")

    with (
        patch("cb_helperd.CONF_PATH", str(conf)),
        patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as run,
    ):
        result = cb_helperd.action_disable_lan_discovery({})
    assert result == {"applied": True}
    assert not override.exists()
    run.assert_called_once_with(
        ["docker", "compose", "-f", "docker-compose.yml", "up", "-d"],
        cwd=str(compose_dir), capture_output=True, text=True, timeout=120,
    )


def test_render_nginx_template_substitutes_variables():
    template = "listen ${CB_PORT};\nserver_name ${server_name};\n"
    result = cb_helperd.render_nginx_template(
        template, {"CB_PORT": "8088", "server_name": "cb.example.com 10.0.0.5 _"}
    )
    assert result == "listen 8088;\nserver_name cb.example.com 10.0.0.5 _;\n"


def test_render_nginx_template_unescapes_nginx_runtime_variables():
    template = r"return 301 https://\$host\$request_uri;"
    result = cb_helperd.render_nginx_template(template, {})
    assert result == "return 301 https://$host$request_uri;"


def test_render_nginx_template_raises_on_missing_variable():
    template = "listen ${CB_PORT};"
    try:
        cb_helperd.render_nginx_template(template, {})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "CB_PORT" in str(exc)


def test_replace_env_keys_updates_existing_and_preserves_rest():
    env_text = "CB_JWT_SECRET=abc123\nCB_FQDN=\nCB_PORT=8088\n# comment\n"
    result = cb_helperd._replace_env_keys(
        env_text, {"CB_FQDN": "cb.example.com", "CB_APP_URL": "https://cb.example.com/"}
    )
    lines = result.splitlines()
    assert "CB_JWT_SECRET=abc123" in lines
    assert "CB_FQDN=cb.example.com" in lines
    assert "CB_PORT=8088" in lines
    assert "# comment" in lines
    assert "CB_APP_URL=https://cb.example.com/" in lines


def test_replace_env_keys_appends_missing_key():
    env_text = "CB_PORT=8088\n"
    result = cb_helperd._replace_env_keys(env_text, {"CB_FQDN": "cb.example.com"})
    assert "CB_FQDN=cb.example.com" in result.splitlines()


def _make_domain_fixture(tmp_path):
    """Sets up a fake native-install layout: .env, nginx conf, tls dir, hosts file."""
    cb_data_dir = tmp_path / "data"
    (cb_data_dir / "tls").mkdir(parents=True)
    (cb_data_dir / "tls" / "fullchain.pem").write_text("ORIGINAL-CERT")
    (cb_data_dir / "tls" / "privkey.pem").write_text("ORIGINAL-KEY")

    env_path = tmp_path / ".env"
    env_path.write_text(
        f"CB_JWT_SECRET=abc123\nCB_DATA_DIR={cb_data_dir}\nCB_PORT=8088\n"
        "CB_FQDN=\nCB_APP_URL=http://192.168.0.45/\n"
    )

    nginx_dest = tmp_path / "circuitbreaker.conf"
    nginx_dest.write_text("ORIGINAL NGINX CONFIG\n")

    hosts_path = tmp_path / "hosts"
    hosts_path.write_text("127.0.0.1 localhost\n")

    template_path = tmp_path / "circuitbreaker-tls.conf"
    template_path.write_text(
        "server {\n  listen ${CB_PORT};\n  server_name ${server_name};\n"
        "  ssl_certificate ${CB_DATA_DIR}/tls/fullchain.pem;\n  return 301 https://\\$host;\n}\n"
    )

    return {
        "cb_data_dir": cb_data_dir,
        "env_path": env_path,
        "nginx_dest": nginx_dest,
        "hosts_path": hosts_path,
        "template_path": template_path,
    }


def _patch_domain_paths(fixture, monkeypatch):
    monkeypatch.setattr(cb_helperd, "ENV_PATH", str(fixture["env_path"]))
    monkeypatch.setattr(cb_helperd, "NGINX_CONF_DEST", str(fixture["nginx_dest"]))
    monkeypatch.setattr(cb_helperd, "NGINX_TLS_TEMPLATE", str(fixture["template_path"]))
    monkeypatch.setattr(cb_helperd, "HOSTS_PATH", str(fixture["hosts_path"]))


def test_configure_domain_happy_path(tmp_path, monkeypatch):
    fixture = _make_domain_fixture(tmp_path)
    _patch_domain_paths(fixture, monkeypatch)

    def _run(cmd, **kwargs):
        if cmd[0] == "openssl":
            fixture_cert = fixture["cb_data_dir"] / "tls" / "fullchain.pem"
            fixture_key = fixture["cb_data_dir"] / "tls" / "privkey.pem"
            fixture_cert.write_text("NEW-CERT")
            fixture_key.write_text("NEW-KEY")
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["ip", "route"]:
            return MagicMock(returncode=0, stdout="1.1.1.1 via 10.0.0.1 src 10.0.0.5\n", stderr="")
        if cmd[:1] == ["nginx"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["systemctl", "reload"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    with (
        patch("subprocess.run", side_effect=_run),
        patch("cb_helperd._https_health_check", return_value=True),
    ):
        result = cb_helperd.action_configure_domain({"fqdn": "cb.example.com"})

    assert result == {
        "applied": True,
        "fqdn": "cb.example.com",
        "app_url": "https://cb.example.com/",
    }
    nginx_out = fixture["nginx_dest"].read_text()
    assert "server_name cb.example.com 10.0.0.5 _;" in nginx_out
    assert "https://$host" in nginx_out  # runtime var survived unescaped
    assert (fixture["cb_data_dir"] / "tls" / "fullchain.pem").read_text() == "NEW-CERT"
    env_out = fixture["env_path"].read_text()
    assert "CB_FQDN=cb.example.com" in env_out
    assert "CB_APP_URL=https://cb.example.com/" in env_out
    assert "cb.example.com" in fixture["hosts_path"].read_text()


def test_configure_domain_requires_fqdn():
    try:
        cb_helperd.action_configure_domain({"fqdn": ""})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "fqdn" in str(exc)


def test_configure_domain_raises_when_no_existing_cert(tmp_path, monkeypatch):
    fixture = _make_domain_fixture(tmp_path)
    (fixture["cb_data_dir"] / "tls" / "fullchain.pem").unlink()
    _patch_domain_paths(fixture, monkeypatch)
    try:
        cb_helperd.action_configure_domain({"fqdn": "cb.example.com"})
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "no existing TLS certificate" in str(exc)


def test_configure_domain_rolls_back_on_nginx_test_failure(tmp_path, monkeypatch):
    fixture = _make_domain_fixture(tmp_path)
    _patch_domain_paths(fixture, monkeypatch)
    original_env = fixture["env_path"].read_text()
    original_nginx = fixture["nginx_dest"].read_text()

    def _run(cmd, **kwargs):
        if cmd[0] == "openssl":
            (fixture["cb_data_dir"] / "tls" / "fullchain.pem").write_text("NEW-CERT")
            (fixture["cb_data_dir"] / "tls" / "privkey.pem").write_text("NEW-KEY")
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["ip", "route"]:
            return MagicMock(returncode=0, stdout="src 10.0.0.5\n", stderr="")
        if cmd[:1] == ["nginx"]:
            return MagicMock(returncode=1, stdout="", stderr="syntax error on line 4")
        if cmd[:2] == ["systemctl", "reload"]:
            return MagicMock(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    with patch("subprocess.run", side_effect=_run):
        try:
            cb_helperd.action_configure_domain({"fqdn": "cb.example.com"})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "syntax error" in str(exc)

    assert fixture["nginx_dest"].read_text() == original_nginx
    assert fixture["env_path"].read_text() == original_env
    assert (fixture["cb_data_dir"] / "tls" / "fullchain.pem").read_text() == "ORIGINAL-CERT"
    assert "cb.example.com" not in fixture["hosts_path"].read_text()


def test_configure_domain_rolls_back_on_health_check_failure(tmp_path, monkeypatch):
    fixture = _make_domain_fixture(tmp_path)
    _patch_domain_paths(fixture, monkeypatch)
    original_nginx = fixture["nginx_dest"].read_text()

    def _run(cmd, **kwargs):
        if cmd[0] == "openssl":
            (fixture["cb_data_dir"] / "tls" / "fullchain.pem").write_text("NEW-CERT")
            (fixture["cb_data_dir"] / "tls" / "privkey.pem").write_text("NEW-KEY")
            return MagicMock(returncode=0, stdout="", stderr="")
        if cmd[:2] == ["ip", "route"]:
            return MagicMock(returncode=0, stdout="src 10.0.0.5\n", stderr="")
        return MagicMock(returncode=0, stdout="", stderr="")

    with (
        patch("subprocess.run", side_effect=_run),
        patch("cb_helperd._https_health_check", return_value=False),
    ):
        try:
            cb_helperd.action_configure_domain({"fqdn": "cb.example.com"})
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "health check" in str(exc)

    assert fixture["nginx_dest"].read_text() == original_nginx
    assert (fixture["cb_data_dir"] / "tls" / "fullchain.pem").read_text() == "ORIGINAL-CERT"
