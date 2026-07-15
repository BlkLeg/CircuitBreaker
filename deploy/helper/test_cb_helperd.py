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
