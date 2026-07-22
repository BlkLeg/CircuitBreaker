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
import re
import shutil
import socket
import ssl
import struct
import subprocess
import time
import urllib.request

SOCKET_PATH = "/run/circuitbreaker/helper.sock"
CONF_PATH = "/etc/circuitbreaker/helper.conf"
ENV_PATH = "/etc/circuitbreaker/.env"
NGINX_TLS_TEMPLATE = "/opt/circuitbreaker/deploy/nginx/circuitbreaker-tls.conf"
NGINX_CONF_DEST = "/etc/nginx/conf.d/circuitbreaker.conf"
HOSTS_PATH = "/etc/hosts"

ALLOWED_ACTIONS = {
    "get_host_readiness",
    "ensure_nmap",
    "grant_nmap_caps",
    "enable_lan_discovery",
    "disable_lan_discovery",
    "configure_domain",
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


def render_nginx_template(template_text: str, variables: dict[str, str]) -> str:
    """Reproduce install.sh's cb_render_template() heredoc semantics in pure
    Python (no eval, no shell): substitute our ${VAR} placeholders, then
    unescape \\$ -> $ so nginx's own runtime variables (\\$host, \\$uri, ...)
    come through literally in the rendered config."""

    def _sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in variables:
            raise RuntimeError(f"template variable not provided: {name}")
        return variables[name]

    rendered = re.sub(r"\$\{(\w+)\}", _sub, template_text)
    rendered = rendered.replace("\\$", "$")
    return rendered


_FQDN_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _is_valid_fqdn(fqdn: str) -> bool:
    """Defense-in-depth syntax check before fqdn is interpolated into a
    cert -subj string and a live nginx config. Deliberately duplicated
    from app.core.hostname_validation rather than imported — this file is
    stdlib-only and isolated from the backend's dependency tree by design."""
    if not fqdn or len(fqdn) > 253:
        return False
    labels = fqdn.split(".")
    if len(labels) < 2 or any(label == "" for label in labels):
        return False
    return all(_FQDN_LABEL_RE.match(label) for label in labels)


def _replace_env_keys(env_text: str, updates: dict[str, str]) -> str:
    """Rewrite only the given KEY=value lines in an .env file, preserving
    every other line (secrets, comments, ordering) byte-for-byte."""
    lines = env_text.splitlines(keepends=True)
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = None
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0]
        if key in updates:
            out.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            out.append(line)
    for key, val in updates.items():
        if key not in seen:
            out.append(f"{key}={val}\n")
    return "".join(out)


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


def _detect_local_ip() -> str | None:
    result = subprocess.run(
        ["ip", "route", "get", "1.1.1.1"], capture_output=True, text=True, timeout=5
    )
    m = re.search(r"src (\S+)", result.stdout)
    return m.group(1) if m else None


def _generate_selfsigned_cert(cert_dir: str, fqdn: str, detected_ip: str | None) -> None:
    san = f"DNS:{fqdn}"
    if detected_ip:
        san += f",IP:{detected_ip}"
    key_path = os.path.join(cert_dir, "privkey.pem")
    cert_path = os.path.join(cert_dir, "fullchain.pem")
    result = subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:4096", "-nodes", "-days", "3650",
            "-keyout", key_path, "-out", cert_path,
            "-subj", f"/CN={fqdn}/O=CircuitBreaker",
            "-addext", f"subjectAltName={san}",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cert generation failed: {result.stderr.strip()[:500]}")


def _add_hosts_entry(fqdn: str) -> bool:
    """Returns True if a line was appended (caller must remove it on rollback)."""
    with open(HOSTS_PATH) as fh:
        if fqdn in fh.read():
            return False
    with open(HOSTS_PATH, "a") as fh:
        fh.write(f"127.0.0.1  {fqdn}\n")
    return True


def _remove_hosts_entry(fqdn: str) -> None:
    with open(HOSTS_PATH) as fh:
        lines = fh.readlines()
    with open(HOSTS_PATH, "w") as fh:
        fh.writelines(line for line in lines if fqdn not in line)


def _https_health_check(cert_path: str, fqdn: str, retries: int = 10, delay: float = 2.0) -> bool:
    """Verifies the nginx+cert stack this action just wrote. Trusts exactly
    the self-signed certificate we generated (a self-signed cert is its own
    CA) and checks the TLS handshake's hostname against fqdn via SNI — this
    proves nginx is serving *our new* certificate for the new domain, not
    merely that some TLS handshake on 443 succeeds. Certificate verification
    is never disabled; there's no CERT_NONE here."""
    ctx = ssl.create_default_context(cafile=cert_path)
    request = f"GET /api/v1/health HTTP/1.1\r\nHost: {fqdn}\r\nConnection: close\r\n\r\n".encode()
    for _ in range(retries):
        try:
            with socket.create_connection(("127.0.0.1", 443), timeout=3) as raw:
                with ctx.wrap_socket(raw, server_hostname=fqdn) as tls:
                    tls.sendall(request)
                    response = b""
                    while True:
                        chunk = tls.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                    status_line = response.split(b"\r\n", 1)[0]
                    if b" 200 " in status_line:
                        return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def action_configure_domain(params: dict) -> dict:
    fqdn = (params.get("fqdn") or "").strip()
    if not fqdn:
        raise RuntimeError("fqdn parameter is required")
    if not _is_valid_fqdn(fqdn):
        raise RuntimeError(f"invalid fqdn: {fqdn!r}")

    env_conf = read_conf(ENV_PATH)
    cb_data_dir = env_conf.get("CB_DATA_DIR")
    cb_port = env_conf.get("CB_PORT")
    if not cb_data_dir or not cb_port:
        raise RuntimeError("CB_DATA_DIR/CB_PORT not found in /etc/circuitbreaker/.env — not a native install?")

    cert_dir = os.path.join(cb_data_dir, "tls")
    cert_path = os.path.join(cert_dir, "fullchain.pem")
    key_path = os.path.join(cert_dir, "privkey.pem")
    if not os.path.isfile(cert_path):
        raise RuntimeError("no existing TLS certificate found — this install was set up without TLS")

    with open(NGINX_CONF_DEST) as fh:
        nginx_snapshot = fh.read()
    with open(cert_path, "rb") as fh:
        cert_snapshot = fh.read()
    with open(key_path, "rb") as fh:
        key_snapshot = fh.read()
    with open(ENV_PATH) as fh:
        env_snapshot = fh.read()
    hosts_entry_added = False

    def _rollback() -> None:
        with open(NGINX_CONF_DEST, "w") as fh:
            fh.write(nginx_snapshot)
        with open(cert_path, "wb") as fh:
            fh.write(cert_snapshot)
        with open(key_path, "wb") as fh:
            fh.write(key_snapshot)
        with open(ENV_PATH, "w") as fh:
            fh.write(env_snapshot)
        if hosts_entry_added:
            _remove_hosts_entry(fqdn)
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True, timeout=15)

    try:
        detected_ip = _detect_local_ip()
        _generate_selfsigned_cert(cert_dir, fqdn, detected_ip)

        server_name = " ".join([fqdn] + ([detected_ip] if detected_ip else []) + ["_"])
        with open(NGINX_TLS_TEMPLATE) as fh:
            template_text = fh.read()
        rendered = render_nginx_template(
            template_text,
            {"CB_PORT": cb_port, "server_name": server_name, "CB_DATA_DIR": cb_data_dir},
        )
        with open(NGINX_CONF_DEST, "w") as fh:
            fh.write(rendered)

        hosts_entry_added = _add_hosts_entry(fqdn)

        app_url = f"https://{fqdn}/"
        new_env_text = _replace_env_keys(env_snapshot, {"CB_FQDN": fqdn, "CB_APP_URL": app_url})
        with open(ENV_PATH, "w") as fh:
            fh.write(new_env_text)

        test_result = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=15)
        if test_result.returncode != 0:
            raise RuntimeError(f"nginx -t failed: {test_result.stderr.strip()[:500]}")

        reload_result = subprocess.run(
            ["systemctl", "reload", "nginx"], capture_output=True, text=True, timeout=15
        )
        if reload_result.returncode != 0:
            raise RuntimeError(f"nginx reload failed: {reload_result.stderr.strip()[:500]}")

        if not _https_health_check(cert_path, fqdn):
            raise RuntimeError("HTTPS health check failed after domain reconfiguration — rolled back")

        return {"applied": True, "fqdn": fqdn, "app_url": app_url}
    except Exception:
        _rollback()
        raise


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
_ACTIONS["configure_domain"] = action_configure_domain


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s cb-helperd %(levelname)s %(message)s")
    serve_forever()
