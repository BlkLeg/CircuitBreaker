import json
import socket
import struct
import threading

import pytest

from app.services import helper_client


def _send(conn, obj):
    body = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack(">I", len(body)) + body)


def _recv(conn):
    header = conn.recv(4)
    (length,) = struct.unpack(">I", header)
    body = b""
    while len(body) < length:
        body += conn.recv(length - len(body))
    return json.loads(body.decode("utf-8"))


def _run_fake_server(sock_path, response):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)

    def _serve():
        conn, _ = server.accept()
        _recv(conn)  # request
        _send(conn, response)
        conn.close()
        server.close()

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    return t


def test_helper_installed_false_when_socket_missing(tmp_path):
    assert helper_client.helper_installed(str(tmp_path / "missing.sock")) is False


def test_helper_installed_true_when_socket_present(tmp_path):
    sock_path = str(tmp_path / "helper.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    try:
        assert helper_client.helper_installed(sock_path) is True
    finally:
        server.close()


def test_call_helper_raises_unavailable_when_socket_missing(tmp_path):
    with pytest.raises(helper_client.HelperUnavailable):
        helper_client.call_helper("get_host_readiness", socket_path=str(tmp_path / "missing.sock"))


def test_call_helper_returns_data_on_success(tmp_path):
    sock_path = str(tmp_path / "helper.sock")
    t = _run_fake_server(sock_path, {"ok": True, "data": {"nmap_present": True}})
    result = helper_client.call_helper("get_host_readiness", socket_path=sock_path)
    t.join(timeout=2)
    assert result == {"nmap_present": True}


def test_call_helper_raises_action_error_on_failure(tmp_path):
    sock_path = str(tmp_path / "helper.sock")
    t = _run_fake_server(sock_path, {"ok": False, "error": "nmap install failed"})
    with pytest.raises(helper_client.HelperActionError, match="nmap install failed"):
        helper_client.call_helper("ensure_nmap", socket_path=sock_path)
    t.join(timeout=2)


def test_convenience_wrappers_call_correct_action(tmp_path, monkeypatch):
    calls = []

    def _fake_call_helper(action, params=None, **kw):
        calls.append(action)
        return {}

    monkeypatch.setattr(helper_client, "call_helper", _fake_call_helper)
    helper_client.get_host_readiness()
    helper_client.ensure_nmap()
    helper_client.grant_nmap_caps()
    helper_client.enable_lan_discovery()
    helper_client.disable_lan_discovery()
    helper_client.configure_domain(fqdn="cb.example.com")
    assert calls == [
        "get_host_readiness",
        "ensure_nmap",
        "grant_nmap_caps",
        "enable_lan_discovery",
        "disable_lan_discovery",
        "configure_domain",
    ]


def test_configure_domain_passes_fqdn_param(monkeypatch):
    captured = {}

    def _fake_call_helper(action, params=None, **kw):
        captured["action"] = action
        captured["params"] = params
        return {"applied": True, "fqdn": "cb.example.com", "app_url": "https://cb.example.com/"}

    monkeypatch.setattr(helper_client, "call_helper", _fake_call_helper)
    result = helper_client.configure_domain("cb.example.com")
    assert captured == {"action": "configure_domain", "params": {"fqdn": "cb.example.com"}}
    assert result["applied"] is True
