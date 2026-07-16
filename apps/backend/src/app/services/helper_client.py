"""Thin client for talking to cb-helperd over its Unix socket.

Degrades gracefully when the helper isn't installed: callers should catch
HelperUnavailable and treat the relevant capability as needs-helper-action,
matching Phase 1's existing readiness states — never crash on a missing
helper.
"""

import json
import os
import socket
import struct

HELPER_SOCKET_PATH = os.environ.get("CB_HELPER_SOCKET_PATH", "/run/circuitbreaker/helper.sock")
_DEFAULT_TIMEOUT = 30.0


class HelperUnavailable(Exception):
    """cb-helperd's socket doesn't exist or refused the connection."""


class HelperActionError(Exception):
    """cb-helperd executed the action but it failed."""


def helper_installed(socket_path: str = HELPER_SOCKET_PATH) -> bool:
    return os.path.exists(socket_path)


def _send_message(conn: socket.socket, obj: dict) -> None:
    body = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack(">I", len(body)) + body)


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("cb-helperd closed the connection")
        buf += chunk
    return buf


def _recv_message(conn: socket.socket) -> dict:
    (length,) = struct.unpack(">I", _recv_exact(conn, 4))
    return json.loads(_recv_exact(conn, length).decode("utf-8"))


def call_helper(
    action: str,
    params: dict | None = None,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
    socket_path: str = HELPER_SOCKET_PATH,
) -> dict:
    if not helper_installed(socket_path):
        raise HelperUnavailable(f"cb-helperd socket not found at {socket_path}")
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    try:
        conn.connect(socket_path)
        _send_message(conn, {"action": action, "params": params or {}})
        response = _recv_message(conn)
    except OSError as exc:
        raise HelperUnavailable(f"cb-helperd connection failed: {exc}") from exc
    finally:
        conn.close()
    if not response.get("ok", False):
        raise HelperActionError(response.get("error", "unknown helper error"))
    return response.get("data", {})


def get_host_readiness(**kw) -> dict:
    return call_helper("get_host_readiness", **kw)


def ensure_nmap(**kw) -> dict:
    return call_helper("ensure_nmap", **kw)


def grant_nmap_caps(**kw) -> dict:
    return call_helper("grant_nmap_caps", **kw)


def enable_lan_discovery(**kw) -> dict:
    return call_helper("enable_lan_discovery", **kw)


def disable_lan_discovery(**kw) -> dict:
    return call_helper("disable_lan_discovery", **kw)
