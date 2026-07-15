#!/usr/bin/env python3
"""cb-helperd — Circuit Breaker privileged host helper.

Runs as root on the host, always outside any container (network_mode can
only be changed from outside the container it applies to). Listens on a
Unix socket and executes a fixed allowlist of actions on behalf of the
unprivileged backend. Stdlib only, no venv — isolated from the backend's
dependency tree since this is the one root-privileged process in the
system; every line here should be reviewable in one sitting.
"""

import json
import logging
import os
import shutil
import socket
import struct
import subprocess
import time
import urllib.request

SOCKET_PATH = "/run/circuitbreaker/helper.sock"
CONF_PATH = "/etc/circuitbreaker/helper.conf"

ALLOWED_ACTIONS = {
    "get_host_readiness",
    "ensure_nmap",
    "grant_nmap_caps",
    "enable_lan_discovery",
    "disable_lan_discovery",
}

logger = logging.getLogger("cb_helperd")

# Populated by Tasks 2-4 (action_* handlers registered here by name).
_ACTIONS: dict = {}


def recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed connection")
        buf += chunk
    return buf


def recv_message(conn: socket.socket) -> dict:
    (length,) = struct.unpack(">I", recv_exact(conn, 4))
    return json.loads(recv_exact(conn, length).decode("utf-8"))


def send_message(conn: socket.socket, obj: dict) -> None:
    body = json.dumps(obj).encode("utf-8")
    conn.sendall(struct.pack(">I", len(body)) + body)


def peer_uid(conn: socket.socket) -> int:
    """SO_PEERCRED is the real authorization boundary; socket file mode is
    defense in depth only."""
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _pid, uid, _gid = struct.unpack("3i", creds)
    return uid


def read_conf(conf_path: str = CONF_PATH) -> dict[str, str]:
    conf: dict[str, str] = {}
    with open(conf_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            conf[k] = v
    return conf


def read_authorized_uid(conf_path: str = CONF_PATH) -> int:
    conf = read_conf(conf_path)
    if "AUTHORIZED_UID" not in conf:
        raise RuntimeError(f"AUTHORIZED_UID not found in {conf_path}")
    return int(conf["AUTHORIZED_UID"])


def dispatch(action: str, params: dict) -> dict:
    if action not in ALLOWED_ACTIONS:
        return {"ok": False, "error": f"unknown action: {action!r}"}
    handler = _ACTIONS.get(action)
    if handler is None:
        return {"ok": False, "error": f"action not implemented: {action!r}"}
    try:
        data = handler(params)
        return {"ok": True, "data": data}
    except Exception as exc:
        logger.exception("action %s failed", action)
        return {"ok": False, "error": str(exc)}


def handle_connection(conn: socket.socket, authorized_uid: int) -> None:
    try:
        uid = peer_uid(conn)
        if uid != authorized_uid:
            logger.warning("rejected connection from unauthorized uid=%s", uid)
            send_message(conn, {"ok": False, "error": "unauthorized"})
            return
        request = recv_message(conn)
        action = request.get("action", "")
        params = request.get("params") or {}
        response = dispatch(action, params)
        send_message(conn, response)
    except Exception:
        logger.exception("connection handling failed")
    finally:
        conn.close()


def serve_forever(sock_path: str = SOCKET_PATH, conf_path: str = CONF_PATH) -> None:
    authorized_uid = read_authorized_uid(conf_path)
    if os.path.exists(sock_path):
        os.remove(sock_path)
    os.makedirs(os.path.dirname(sock_path), exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    os.chmod(sock_path, 0o660)
    server.listen(5)
    logger.info("cb-helperd listening on %s", sock_path)
    try:
        while True:
            conn, _ = server.accept()
            handle_connection(conn, authorized_uid)
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.remove(sock_path)


OVERRIDE_FILENAME = "docker-compose.lan-discovery.yml"

_LAN_DISCOVERY_OVERRIDE_TEMPLATE = """# Circuit Breaker — LAN discovery override (managed by cb-helperd)
# Generated automatically. Do not edit by hand — changes are overwritten.
services:
  circuitbreaker:
    network_mode: host
    cap_add:
      - NET_RAW
"""


def _compose_snapshot(compose_dir: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config"],
        cwd=compose_dir, capture_output=True, text=True, timeout=30,
    )
    return result.stdout


def _compose_up(compose_dir: str, override_filename: str):
    return subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", override_filename, "up", "-d"],
        cwd=compose_dir, capture_output=True, text=True, timeout=120,
    )


def _compose_up_base_only(compose_dir: str):
    return subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "up", "-d"],
        cwd=compose_dir, capture_output=True, text=True, timeout=120,
    )


def _health_check(retries: int = 10, delay: float = 2.0) -> bool:
    for _ in range(retries):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/api/v1/health", timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def action_enable_lan_discovery(_params: dict) -> dict:
    conf = read_conf(CONF_PATH)
    compose_dir = conf.get("COMPOSE_DIR", "")
    if not compose_dir:
        return {"applied": False, "reason": "bare-metal install — already on the LAN, no action needed"}

    base_compose = os.path.join(compose_dir, "docker-compose.yml")
    if not os.path.isfile(base_compose):
        raise RuntimeError(f"base compose file not found at {base_compose}")

    _compose_snapshot(compose_dir)  # validated the base config is readable before mutating
    override_path = os.path.join(compose_dir, OVERRIDE_FILENAME)
    with open(override_path, "w") as fh:
        fh.write(_LAN_DISCOVERY_OVERRIDE_TEMPLATE)

    result = _compose_up(compose_dir, OVERRIDE_FILENAME)
    if result.returncode != 0:
        os.remove(override_path)
        _compose_up_base_only(compose_dir)
        raise RuntimeError(f"docker compose up failed: {result.stderr.strip()[:1000]}")

    if not _health_check():
        os.remove(override_path)
        _compose_up_base_only(compose_dir)
        raise RuntimeError("container failed health check after recreation — rolled back")

    return {"applied": True, "override_path": override_path}


def action_disable_lan_discovery(_params: dict) -> dict:
    conf = read_conf(CONF_PATH)
    compose_dir = conf.get("COMPOSE_DIR", "")
    if not compose_dir:
        return {"applied": False, "reason": "bare-metal install — nothing to disable"}

    override_path = os.path.join(compose_dir, OVERRIDE_FILENAME)
    if not os.path.isfile(override_path):
        return {"applied": True, "reason": "override already absent"}

    os.remove(override_path)
    result = _compose_up_base_only(compose_dir)
    if result.returncode != 0:
        raise RuntimeError(f"docker compose recreation (disable) failed: {result.stderr.strip()[:1000]}")
    return {"applied": True}


def detect_pkg_manager() -> str | None:
    for mgr in ("apt-get", "dnf", "pacman"):
        if shutil.which(mgr):
            return mgr
    return None


def action_ensure_nmap(_params: dict) -> dict:
    if shutil.which("nmap"):
        return {"already_present": True}
    mgr = detect_pkg_manager()
    if mgr is None:
        raise RuntimeError("No supported package manager found (apt-get, dnf, pacman)")
    if mgr == "apt-get":
        cmd = ["apt-get", "install", "-y", "-q", "nmap"]
    elif mgr == "dnf":
        cmd = ["dnf", "install", "-y", "-q", "nmap"]
    else:
        cmd = ["pacman", "-S", "--noconfirm", "--needed", "nmap"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"nmap install failed ({mgr}): {result.stderr.strip()[:500]}")
    if not shutil.which("nmap"):
        raise RuntimeError("nmap install reported success but binary still not on PATH")
    return {"already_present": False, "package_manager": mgr}


def action_grant_nmap_caps(_params: dict) -> dict:
    nmap_path = shutil.which("nmap")
    if not nmap_path:
        raise RuntimeError("nmap binary not found — run ensure_nmap first")
    result = subprocess.run(
        ["setcap", "cap_net_raw+eip", nmap_path], capture_output=True, text=True, timeout=10
    )
    if result.returncode != 0:
        raise RuntimeError(f"setcap failed: {result.stderr.strip()[:500]}")
    return {"nmap_path": nmap_path}


def _nmap_has_raw_cap() -> bool:
    nmap_path = shutil.which("nmap")
    if not nmap_path:
        return False
    try:
        result = subprocess.run(["getcap", nmap_path], capture_output=True, text=True, timeout=5)
        return "cap_net_raw" in result.stdout
    except Exception:
        return False


def action_get_host_readiness(_params: dict) -> dict:
    return {
        "nmap_present": shutil.which("nmap") is not None,
        "nmap_capped": _nmap_has_raw_cap(),
        "docker_available": shutil.which("docker") is not None,
    }


_ACTIONS["ensure_nmap"] = action_ensure_nmap
_ACTIONS["grant_nmap_caps"] = action_grant_nmap_caps
_ACTIONS["get_host_readiness"] = action_get_host_readiness
_ACTIONS["enable_lan_discovery"] = action_enable_lan_discovery
_ACTIONS["disable_lan_discovery"] = action_disable_lan_discovery


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s cb-helperd %(levelname)s %(message)s")
    serve_forever()
