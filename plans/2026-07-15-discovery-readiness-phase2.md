# Discovery Readiness Phase 2 — `cb-helperd` Broker & Self-Healing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `cb-helperd` (a minimal root host daemon), `helper_client.py` (the backend's client for it), and a self-healing reconciliation loop so LAN-discovery adjacency and Class-1 drift repair no longer require the user to touch a terminal or click a "Fix" button more than once.

**Architecture:** `cb-helperd` runs as root on the host (bare-metal or Docker host, never inside a container), listens on a Unix socket, and executes a fixed allowlist of actions (`get_host_readiness`, `ensure_nmap`, `grant_nmap_caps`, `enable_lan_discovery`, `disable_lan_discovery`). The backend's `helper_client.py` speaks the same length-prefixed JSON protocol. A new `discovery_reconciler.py`, registered with the existing APScheduler instance (`app/core/scheduler.py`) and guarded by the existing Postgres advisory-lock helper (`app/core/job_lock.py`), calls the helper on a schedule: Class-1 capabilities (`nmap_present`, `nmap_raw`) are healed unconditionally on drift; Class-2 (LAN discovery) is converged toward a new persisted `lan_discovery_desired` setting that only the user's one-time toggle changes.

**Tech Stack:** Python 3.14 stdlib only for `cb_helperd.py` (no third-party deps, no venv — isolated from the backend's dependency tree). Backend side: FastAPI, SQLAlchemy, APScheduler (`AsyncIOScheduler`, already running), pytest (`asyncio_mode = "auto"`).

**Spec:** `specs/2026-07-15-discovery-readiness-phase2-helper-design.md`. Builds on Phase 1 (`specs/2026-07-14-discovery-readiness-capability-broker-design.md`, `plans/2026-07-14-discovery-readiness-phase1.md`), which is complete and committed.

## Global Constraints

- Backend source lives under `apps/backend/src/app/`; tests under `apps/backend/tests/`.
- Tests use `pytest` with `asyncio_mode = "auto"` — async tests need **no** `@pytest.mark.asyncio` decorator.
- `cb_helperd.py` (`deploy/helper/cb_helperd.py`) is **stdlib-only** — no imports outside the Python standard library. It is run directly by systemd with the system Python interpreter, no venv.
- The capability **key**/**state** vocabulary from Phase 1 stays exactly as-is: keys `nmap_present`, `nmap_raw`, `arp_l2`, `lan_adjacency`; states `ready`, `auto-fixable`, `needs-helper-action`, `unavailable-on-platform` (`app/services/discovery_readiness.py`, `CapState` enum).
- The helper's action allowlist is exactly these five strings, used verbatim everywhere: `get_host_readiness`, `ensure_nmap`, `grant_nmap_caps`, `enable_lan_discovery`, `disable_lan_discovery`.
- Never pass unvalidated strings to a subprocess. `cb_helperd.py` actions only ever invoke a fixed, hardcoded argv list — no string formatting into a shell.
- `SO_PEERCRED` authorizes exactly one numeric uid, read from `/etc/circuitbreaker/helper.conf` (`AUTHORIZED_UID=...`), not a group name.
- The mono container's `breaker` user is a fixed `uid=1000, gid=1000` (`Dockerfile.mono:144-145`) — the Docker-path `helper.conf` always writes `AUTHORIZED_UID=1000`. Bare-metal writes `AUTHORIZED_UID=$(id -u breaker)` since `deploy/setup.sh` allows a custom uid at install time.
- Every helper action's success or failure is logged via `app/core/worker_audit.py:log_worker_audit` (no `Request` object needed — this is the established convention for background/system-attributed audit entries, already used by `_vault_rotation_check` and other scheduled jobs in `main.py`).

---

### Task 1: `cb_helperd.py` — wire protocol, peer auth, dispatch skeleton, server loop

**Files:**
- Create: `deploy/helper/cb_helperd.py`
- Test: `deploy/helper/test_cb_helperd.py`

**Interfaces:**
- Produces: `recv_exact(conn, n) -> bytes`, `recv_message(conn) -> dict`, `send_message(conn, obj) -> None`, `peer_uid(conn) -> int`, `read_authorized_uid(conf_path) -> int`, `read_conf(conf_path) -> dict[str, str]`, `dispatch(action, params) -> dict`, `handle_connection(conn, authorized_uid) -> None`, `serve_forever(sock_path, conf_path) -> None`. `ALLOWED_ACTIONS: set[str]`. These are consumed by Tasks 2–4 (which add action handlers to the `_ACTIONS` dict) and by `helper_client.py` (Task 7), which implements the same wire format independently.

- [ ] **Step 1: Write the failing tests for framing and auth**

```python
# deploy/helper/test_cb_helperd.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cb_helperd'`.

- [ ] **Step 3: Write `cb_helperd.py`**

```python
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
import socket
import struct

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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s cb-helperd %(levelname)s %(message)s")
    serve_forever()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add deploy/helper/cb_helperd.py deploy/helper/test_cb_helperd.py
git commit -m "feat(helper): cb-helperd protocol framing, SO_PEERCRED auth, dispatch skeleton"
```

---

### Task 2: `cb_helperd.py` — `ensure_nmap` and `grant_nmap_caps` actions

**Files:**
- Modify: `deploy/helper/cb_helperd.py`
- Test: `deploy/helper/test_cb_helperd.py`

**Interfaces:**
- Consumes: `_ACTIONS` dict from Task 1.
- Produces: `detect_pkg_manager() -> str | None`, `action_ensure_nmap(params) -> dict`, `action_grant_nmap_caps(params) -> dict`. Registered into `_ACTIONS["ensure_nmap"]` / `_ACTIONS["grant_nmap_caps"]`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to deploy/helper/test_cb_helperd.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v -k "ensure_nmap or grant_nmap_caps or pkg_manager"`
Expected: FAIL — `AttributeError: module 'cb_helperd' has no attribute 'detect_pkg_manager'`.

- [ ] **Step 3: Add the implementation**

```python
# Add near the top of deploy/helper/cb_helperd.py, after the existing imports
import shutil
import subprocess
```

```python
# Append to deploy/helper/cb_helperd.py, before the `if __name__ == "__main__":` block

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


_ACTIONS["ensure_nmap"] = action_ensure_nmap
_ACTIONS["grant_nmap_caps"] = action_grant_nmap_caps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v`
Expected: PASS (16 passed).

- [ ] **Step 5: Commit**

```bash
git add deploy/helper/cb_helperd.py deploy/helper/test_cb_helperd.py
git commit -m "feat(helper): ensure_nmap and grant_nmap_caps actions"
```

---

### Task 3: `cb_helperd.py` — `get_host_readiness` action

**Files:**
- Modify: `deploy/helper/cb_helperd.py`
- Test: `deploy/helper/test_cb_helperd.py`

**Interfaces:**
- Produces: `action_get_host_readiness(params) -> dict` with keys `nmap_present: bool`, `nmap_capped: bool`, `docker_available: bool`. Registered into `_ACTIONS["get_host_readiness"]`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to deploy/helper/test_cb_helperd.py

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v -k get_host_readiness`
Expected: FAIL — `AttributeError: module 'cb_helperd' has no attribute 'action_get_host_readiness'`.

- [ ] **Step 3: Add the implementation**

```python
# Append to deploy/helper/cb_helperd.py, before the `_ACTIONS["ensure_nmap"] = ...` lines

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
```

```python
# Extend the registration block at the bottom of deploy/helper/cb_helperd.py
_ACTIONS["get_host_readiness"] = action_get_host_readiness
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v`
Expected: PASS (18 passed).

- [ ] **Step 5: Commit**

```bash
git add deploy/helper/cb_helperd.py deploy/helper/test_cb_helperd.py
git commit -m "feat(helper): get_host_readiness action"
```

---

### Task 4: `cb_helperd.py` — `enable_lan_discovery` / `disable_lan_discovery` actions

**Files:**
- Modify: `deploy/helper/cb_helperd.py`
- Test: `deploy/helper/test_cb_helperd.py`

**Interfaces:**
- Consumes: `read_conf` from Task 1.
- Produces: `action_enable_lan_discovery(params) -> dict`, `action_disable_lan_discovery(params) -> dict`. Registered into `_ACTIONS`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to deploy/helper/test_cb_helperd.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v -k lan_discovery`
Expected: FAIL — `AttributeError: module 'cb_helperd' has no attribute 'action_enable_lan_discovery'`.

- [ ] **Step 3: Add the implementation**

```python
# Add near the top of deploy/helper/cb_helperd.py, after the existing imports
import time
import urllib.request
```

```python
# Append to deploy/helper/cb_helperd.py, before the `_ACTIONS["ensure_nmap"] = ...` lines

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
```

```python
# Extend the registration block at the bottom of deploy/helper/cb_helperd.py
_ACTIONS["enable_lan_discovery"] = action_enable_lan_discovery
_ACTIONS["disable_lan_discovery"] = action_disable_lan_discovery
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd deploy/helper && /home/shawnji/workspace/CircuitBreaker/.venv/bin/python -m pytest test_cb_helperd.py -v`
Expected: PASS (26 passed).

- [ ] **Step 5: Commit**

```bash
git add deploy/helper/cb_helperd.py deploy/helper/test_cb_helperd.py
git commit -m "feat(helper): enable/disable_lan_discovery actions with snapshot+rollback"
```

---

### Task 5: `deploy/systemd/cb-helperd.service`

**Files:**
- Create: `deploy/systemd/cb-helperd.service`

Pattern-matches `deploy/systemd/circuitbreaker-backend.service` but runs as root (no `User=`/`Group=` line) since it must retain root for `apt`/`setcap`/`docker compose` actions.

- [ ] **Step 1: Write the unit file**

```ini
[Unit]
Description=Circuit Breaker Privileged Helper (cb-helperd)
Documentation=https://github.com/BlkLeg/CircuitBreaker
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/circuitbreaker/deploy/helper/cb_helperd.py
Restart=on-failure
RestartSec=5s
RuntimeDirectory=circuitbreaker
RuntimeDirectoryMode=0755
NoNewPrivileges=false
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cb-helperd

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Validate unit syntax**

Run: `systemd-analyze verify deploy/systemd/cb-helperd.service 2>&1 || true`
Expected: no `Failed to load` errors relating to this file (a warning about a relative `ExecStart` path not existing at verify-time in this repo checkout is expected and fine — the path is absolute and correct for the installed location `/opt/circuitbreaker/...`).

- [ ] **Step 3: Commit**

```bash
git add deploy/systemd/cb-helperd.service
git commit -m "feat(helper): cb-helperd systemd unit"
```

---

### Task 6: Migration + `AppSettings` model + schemas — `lan_discovery_desired`

**Files:**
- Create: `apps/backend/migrations/versions/0084_lan_discovery_desired_setting.py`
- Modify: `apps/backend/src/app/db/models.py:944-948` (near `docker_sync_interval_minutes`)
- Modify: `apps/backend/src/app/schemas/settings.py:143-146` and `:411-413`
- Modify: `apps/backend/src/app/services/settings_service.py:60-61` (`_DEFAULTS`)

**Interfaces:**
- Produces: `AppSettings.lan_discovery_desired: bool` (default `False`), exposed on `SettingsOut`/`AppSettingsUpdate`. Consumed by Task 9 (`discovery_reconciler.py`).

- [ ] **Step 1: Write the migration**

The current alembic head is `7c41a90d55e1` (`create_network_privacy_snapshots`) — confirmed via the `down_revision` chain in `apps/backend/migrations/versions/`.

```python
# apps/backend/migrations/versions/0084_lan_discovery_desired_setting.py
"""Add lan_discovery_desired toggle to app_settings

Revision ID: 0084_lan_discovery_desired_setting
Revises: 7c41a90d55e1
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0084_lan_discovery_desired_setting"
down_revision = "7c41a90d55e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0084")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings '
            "ADD COLUMN IF NOT EXISTS lan_discovery_desired BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0084")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings DROP COLUMN IF EXISTS lan_discovery_desired'
        )
    )
```

- [ ] **Step 2: Add the model column**

In `apps/backend/src/app/db/models.py`, right after line 948 (`docker_sync_interval_minutes`):

```python
    docker_sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Phase 2 discovery-readiness: persisted user consent for LAN discovery.
    # Set only by the explicit toggle; the reconciler converges actual state
    # to this value, never the other way around.
    lan_discovery_desired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
```

- [ ] **Step 3: Add the schema fields**

In `apps/backend/src/app/schemas/settings.py`, in the settings-out class (near line 145, after `docker_sync_interval_minutes: int = 5`):

```python
    docker_sync_interval_minutes: int = 5
    lan_discovery_desired: bool = False
```

And in the update class (near line 413, after `docker_sync_interval_minutes: int | None = None`):

```python
    docker_sync_interval_minutes: int | None = None
    lan_discovery_desired: bool | None = None
```

- [ ] **Step 4: Add the default**

In `apps/backend/src/app/services/settings_service.py`, in `_DEFAULTS` (near line 61, after `docker_sync_interval_minutes=5,`):

```python
    docker_sync_interval_minutes=5,
    lan_discovery_desired=False,
```

- [ ] **Step 5: Write a test that the setting round-trips**

```python
# apps/backend/tests/test_settings_lan_discovery.py
from app.schemas.settings import AppSettingsUpdate
from app.services.settings_service import get_or_create_settings, update_settings


def test_lan_discovery_desired_defaults_false(db_session):
    settings = get_or_create_settings(db_session)
    assert settings.lan_discovery_desired is False


def test_lan_discovery_desired_can_be_toggled(db_session):
    update_settings(db_session, AppSettingsUpdate(lan_discovery_desired=True))
    settings = get_or_create_settings(db_session)
    assert settings.lan_discovery_desired is True
```

`db_session` is the standard per-test DB session fixture defined in `apps/backend/tests/conftest.py:96`, already used across the test suite — no substitution needed.

- [ ] **Step 6: Run the migration and the test**

Run: `cd apps/backend && python -m alembic upgrade head && python -m pytest tests/test_settings_lan_discovery.py -v`
Expected: migration applies with no errors; PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add apps/backend/migrations/versions/0084_lan_discovery_desired_setting.py \
        apps/backend/src/app/db/models.py apps/backend/src/app/schemas/settings.py \
        apps/backend/src/app/services/settings_service.py \
        apps/backend/tests/test_settings_lan_discovery.py
git commit -m "feat(settings): add lan_discovery_desired persisted toggle"
```

---

### Task 7: `helper_client.py`

**Files:**
- Create: `apps/backend/src/app/services/helper_client.py`
- Test: `apps/backend/tests/test_helper_client.py`

**Interfaces:**
- Produces: `HELPER_SOCKET_PATH: str`, `HelperUnavailable(Exception)`, `HelperActionError(Exception)`, `helper_installed(socket_path=HELPER_SOCKET_PATH) -> bool`, `call_helper(action, params=None, *, timeout=30.0, socket_path=HELPER_SOCKET_PATH) -> dict`, `get_host_readiness(**kw)`, `ensure_nmap(**kw)`, `grant_nmap_caps(**kw)`, `enable_lan_discovery(**kw)`, `disable_lan_discovery(**kw)`. Consumed by Task 9 (`discovery_reconciler.py`).
- Speaks the exact wire protocol implemented independently in `deploy/helper/cb_helperd.py` (Task 1): 4-byte big-endian length prefix + UTF-8 JSON body, both directions.

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/test_helper_client.py
import json
import os
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
    assert calls == [
        "get_host_readiness",
        "ensure_nmap",
        "grant_nmap_caps",
        "enable_lan_discovery",
        "disable_lan_discovery",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_helper_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.helper_client'`.

- [ ] **Step 3: Write `helper_client.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_helper_client.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/helper_client.py apps/backend/tests/test_helper_client.py
git commit -m "feat(discovery): helper_client — Unix socket client for cb-helperd"
```

---

### Task 8: `docker-compose.yml` — bind mount for the helper socket

**Files:**
- Modify: `docker-compose.yml:25-26`

**Interfaces:** none (infrastructure config only).

- [ ] **Step 1: Add the bind mount**

In `docker-compose.yml`, change:

```yaml
    volumes:
      - "${CB_DATA_DIR:-./circuitbreaker-data}:/data:z"
```

to:

```yaml
    volumes:
      - "${CB_DATA_DIR:-./circuitbreaker-data}:/data:z"
      # cb-helperd's socket (host-side root daemon, Phase 2 discovery-readiness
      # broker). Harmless if cb-helperd isn't installed — the path just won't
      # exist inside the container and helper_client degrades gracefully.
      - /run/circuitbreaker:/run/circuitbreaker
```

- [ ] **Step 2: Validate compose syntax**

Run: `docker compose -f docker-compose.yml config --quiet && echo OK`
Expected: `OK`, no errors. (This will fail with a "Set CB_DB_PASSWORD" etc. error if those env vars aren't set in the shell — that's pre-existing behavior unrelated to this change; export dummy values first if needed: `CB_DB_PASSWORD=x CB_VAULT_KEY=x CB_JWT_SECRET=x NATS_AUTH_TOKEN=x docker compose -f docker-compose.yml config --quiet && echo OK`.)

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(helper): bind-mount cb-helperd socket into the mono container"
```

---

### Task 9: Installer wiring — `install.sh` and `deploy/setup.sh`

**Files:**
- Modify: `install.sh` (new function `cb_install_helper_daemon`, called from `stage_docker_deploy`)
- Modify: `deploy/setup.sh` (new function `stage_configure_helper`, called alongside the existing systemd-unit stage)
- Create: `deploy/misc/` is not needed — the unit file already lives in `deploy/systemd/cb-helperd.service` (Task 5) and `deploy/helper/cb_helperd.py` (Task 1), both already shipped as part of the repo bundle copied to `/opt/circuitbreaker` by both installers' existing bundle-copy steps.

**Interfaces:** none (shell only). Writes `/etc/circuitbreaker/helper.conf` consumed by `cb_helperd.py` (Task 1) and creates `/run/circuitbreaker` consumed by both `cb_helperd.py` and `helper_client.py` (Task 7).

- [ ] **Step 1: Add `cb_install_helper_daemon` to `install.sh`**

Add this function right after `cb_install_docker_if_missing` (after its closing `}` around line 191), reusing the same `root_prefix` sudo-escalation pattern that function already uses:

```bash
cb_install_helper_daemon() {
  local install_dir="$1"

  cb_step "Installing cb-helperd (privileged host helper)"
  local root_prefix=()
  if [[ $EUID -ne 0 ]]; then
    if ! command -v sudo >/dev/null 2>&1; then
      cb_warn "sudo unavailable — skipping cb-helperd install (LAN discovery and auto-repair need it)"
      return 0
    fi
    root_prefix=(sudo)
  fi

  "${root_prefix[@]}" mkdir -p /opt/circuitbreaker/deploy/helper /etc/circuitbreaker /run/circuitbreaker
  "${root_prefix[@]}" cp "${install_dir}/deploy/helper/cb_helperd.py" /opt/circuitbreaker/deploy/helper/cb_helperd.py
  "${root_prefix[@]}" cp "${install_dir}/deploy/systemd/cb-helperd.service" /etc/systemd/system/cb-helperd.service

  # The mono image's breaker user is a fixed uid=1000 (Dockerfile.mono) —
  # always correct for the Docker deploy path regardless of the host user
  # running this installer.
  "${root_prefix[@]}" bash -c "cat > /etc/circuitbreaker/helper.conf" <<EOF
AUTHORIZED_UID=1000
COMPOSE_DIR=${install_dir}
EOF
  "${root_prefix[@]}" chmod 640 /etc/circuitbreaker/helper.conf

  "${root_prefix[@]}" systemctl daemon-reload
  "${root_prefix[@]}" systemctl enable --now cb-helperd >/dev/null 2>&1 \
    || cb_warn "cb-helperd failed to start — check: systemctl status cb-helperd"
  cb_ok "cb-helperd installed and running"
}
```

- [ ] **Step 2: Call it from `stage_docker_deploy`**

In `install.sh`, `stage_docker_deploy` currently ends with the "Docker stack is running" block (around line 256-257). Locate:

```bash
  cb_step "Starting stack with docker compose"
  (
    cd "${install_dir}" && docker compose up -d
  ) || cb_fail "Docker Compose deployment failed" "Run: cd ${install_dir} && docker compose logs --tail=80"
  cb_ok "Docker stack is running"
```

and insert the helper install call right after it, before the `local host_ip` block:

```bash
  cb_step "Starting stack with docker compose"
  (
    cd "${install_dir}" && docker compose up -d
  ) || cb_fail "Docker Compose deployment failed" "Run: cd ${install_dir} && docker compose logs --tail=80"
  cb_ok "Docker stack is running"

  cb_install_helper_daemon "${install_dir}"

  local host_ip
```

Also add `deploy/helper` to the assets downloaded earlier in the same function — find the "Downloading official compose assets" block (around line 227-230) and add the helper script + unit alongside the existing curls:

```bash
  cb_step "Downloading official compose assets"
  curl -fsSL "${base_url}/docker-compose.yml" -o "${install_dir}/docker-compose.yml"
  curl -fsSL "${base_url}/docker/docker-compose.socket.yml" -o "${install_dir}/docker/docker-compose.socket.yml"
  curl -fsSL "${base_url}/.env.example" -o "${install_dir}/.env.example"
  mkdir -p "${install_dir}/deploy/helper" "${install_dir}/deploy/systemd"
  curl -fsSL "${base_url}/deploy/helper/cb_helperd.py" -o "${install_dir}/deploy/helper/cb_helperd.py"
  curl -fsSL "${base_url}/deploy/systemd/cb-helperd.service" -o "${install_dir}/deploy/systemd/cb-helperd.service"
  cb_ok "Compose assets downloaded"
```

- [ ] **Step 3: Add `stage_configure_helper` to `deploy/setup.sh`**

Add this function right after `stage3_configure_docker_proxy` (after its closing `}` around line 793):

```bash
stage_configure_helper() {
  cb_section "Configuring cb-helperd (privileged host helper)"

  mkdir -p /run/circuitbreaker
  local breaker_uid
  breaker_uid="$(id -u breaker)"

  cb_step "Writing /etc/circuitbreaker/helper.conf"
  cat > /etc/circuitbreaker/helper.conf <<EOF
AUTHORIZED_UID=${breaker_uid}
EOF
  chmod 640 /etc/circuitbreaker/helper.conf
  cb_ok "helper.conf written (AUTHORIZED_UID=${breaker_uid})"

  cp "/opt/circuitbreaker/deploy/systemd/cb-helperd.service" "/etc/systemd/system/cb-helperd.service"
  systemctl daemon-reload >> "$LOG_FILE" 2>&1
  systemctl enable --now cb-helperd >> "$LOG_FILE" 2>&1 \
    || cb_warn "cb-helperd failed to start — check: systemctl status cb-helperd"
  cb_ok "cb-helperd enabled"
}
```

Note: bare-metal's `helper.conf` has no `COMPOSE_DIR` line — `cb_helperd.py`'s `action_enable_lan_discovery`/`action_disable_lan_discovery` (Task 4) already treat a missing `COMPOSE_DIR` as the correct bare-metal no-op ("already on the LAN").

- [ ] **Step 4: Call `stage_configure_helper` from the systemd-units stage**

In `deploy/setup.sh`, immediately after the block that ends with `cb_ok "Systemd units created and enabled"` (around line 884), add:

```bash
  cb_ok "Systemd units created and enabled"

  stage_configure_helper
```

- [ ] **Step 5: Shellcheck both scripts**

Run: `shellcheck install.sh deploy/setup.sh`
Expected: no new warnings introduced by this change (pre-existing warnings elsewhere in these files, if any, are out of scope).

- [ ] **Step 6: Commit**

```bash
git add install.sh deploy/setup.sh
git commit -m "feat(helper): install and enable cb-helperd on both deploy paths"
```

---

### Task 10: `core/constants.py` — reconciler cadence constants

**Files:**
- Modify: `apps/backend/src/app/core/constants.py`

**Interfaces:**
- Produces: `DISCOVERY_RECONCILE_INTERVAL_MINUTES = 15`, `DISCOVERY_RECONCILE_BACKOFF_MINUTES = 60`, `DISCOVERY_RECONCILE_FAILURE_THRESHOLD = 3`. Consumed by Task 11 (`discovery_reconciler.py`).

- [ ] **Step 1: Add the constants**

In `apps/backend/src/app/core/constants.py`, right after `PRIVACY_PERIODIC_INTERVAL_MINUTES = 15` (line 42):

```python
PRIVACY_PERIODIC_INTERVAL_MINUTES = 15

# Discovery-readiness Phase 2: self-healing reconciliation cadence.
# Normal cadence matches the existing privacy-periodic job for consistency.
# After DISCOVERY_RECONCILE_FAILURE_THRESHOLD consecutive failures for a
# given capability, its retry cadence drops to the backoff interval rather
# than being abandoned outright.
DISCOVERY_RECONCILE_INTERVAL_MINUTES = 15
DISCOVERY_RECONCILE_BACKOFF_MINUTES = 60
DISCOVERY_RECONCILE_FAILURE_THRESHOLD = 3
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/src/app/core/constants.py
git commit -m "feat(discovery): reconciler cadence constants"
```

---

### Task 11: `discovery_reconciler.py` — Class-1 auto-heal, Class-2 convergence, backoff

**Files:**
- Create: `apps/backend/src/app/services/discovery_reconciler.py`
- Test: `apps/backend/tests/test_discovery_reconciler.py`

**Interfaces:**
- Consumes: `app.services.discovery_readiness.get_discovery_readiness`, `CapState` (Phase 1); `app.services.helper_client` (Task 7); `app.core.worker_audit.log_worker_audit`; `app.core.job_lock.run_with_advisory_lock`; `app.services.settings_service.get_or_create_settings`; `app.db.session.SessionLocal`; constants from Task 10.
- Produces: `run_discovery_reconciliation() -> None` (sync — the APScheduler entry point, wired in Task 12), `reset_reconciler_state_for_tests() -> None` (test-only helper to clear module-level backoff state between tests).

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/test_discovery_reconciler.py
from unittest.mock import MagicMock, patch

import pytest

from app.services import discovery_reconciler as reconciler
from app.services.discovery_readiness import CapState, Capability


def _cap(key, state):
    return Capability(key=key, title=key, state=state, explanation="", reason_code="")


@pytest.fixture(autouse=True)
def _reset_state():
    reconciler.reset_reconciler_state_for_tests()
    yield
    reconciler.reset_reconciler_state_for_tests()


def test_reconcile_class1_heals_auto_fixable_nmap_present():
    caps = [
        _cap("nmap_present", CapState.AUTO_FIXABLE),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=True),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_called_once()


def test_reconcile_class1_skips_when_already_ready():
    caps = [
        _cap("nmap_present", CapState.READY),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=True),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
        patch("app.services.discovery_reconciler.helper_client.grant_nmap_caps") as grant_caps,
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_not_called()
        grant_caps.assert_not_called()


def test_reconcile_class1_skips_without_helper_installed():
    caps = [_cap("nmap_present", CapState.AUTO_FIXABLE), _cap("nmap_raw", CapState.READY)]
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=False),
        patch("app.services.discovery_reconciler.helper_client.ensure_nmap") as ensure_nmap,
    ):
        reconciler._reconcile_class1()
        ensure_nmap.assert_not_called()


def test_attempt_heal_backoff_after_threshold_failures():
    with patch("app.services.discovery_reconciler.log_worker_audit"):
        for _ in range(3):
            reconciler._attempt_heal("nmap_present", "ensure_nmap", MagicMock(side_effect=RuntimeError("boom")))
        state = reconciler._STATE["nmap_present"]
        assert state["failures"] == 3
        # Next _due() check should be gated by the longer backoff window,
        # i.e. not due again immediately.
        assert reconciler._due("nmap_present") is False


def test_attempt_heal_resets_backoff_on_success():
    with patch("app.services.discovery_reconciler.log_worker_audit"):
        reconciler._attempt_heal("nmap_present", "ensure_nmap", MagicMock(side_effect=RuntimeError("boom")))
        reconciler._attempt_heal("nmap_present", "ensure_nmap", MagicMock(return_value={}))
        state = reconciler._STATE["nmap_present"]
        assert state["failures"] == 0


def test_reconcile_class2_enables_when_desired_and_not_actual():
    caps = [_cap("arp_l2", CapState.NEEDS_HELPER_ACTION)]
    settings_row = MagicMock(lan_discovery_desired=True)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=True),
        patch("app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row),
        patch("app.services.discovery_reconciler.helper_client.enable_lan_discovery") as enable,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class2(db=MagicMock())
        enable.assert_called_once()


def test_reconcile_class2_disables_when_not_desired_but_actual():
    caps = [_cap("arp_l2", CapState.READY)]
    settings_row = MagicMock(lan_discovery_desired=False)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=True),
        patch("app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row),
        patch("app.services.discovery_reconciler.helper_client.disable_lan_discovery") as disable,
        patch("app.services.discovery_reconciler.log_worker_audit"),
    ):
        reconciler._reconcile_class2(db=MagicMock())
        disable.assert_called_once()


def test_reconcile_class2_noop_when_state_matches_desired():
    caps = [_cap("arp_l2", CapState.READY)]
    settings_row = MagicMock(lan_discovery_desired=True)
    with (
        patch("app.services.discovery_reconciler.get_discovery_readiness", return_value=caps),
        patch("app.services.discovery_reconciler.helper_client.helper_installed", return_value=True),
        patch("app.services.discovery_reconciler.get_or_create_settings", return_value=settings_row),
        patch("app.services.discovery_reconciler.helper_client.enable_lan_discovery") as enable,
        patch("app.services.discovery_reconciler.helper_client.disable_lan_discovery") as disable,
    ):
        reconciler._reconcile_class2(db=MagicMock())
        enable.assert_not_called()
        disable.assert_not_called()


def test_run_discovery_reconciliation_uses_advisory_lock():
    with patch("app.services.discovery_reconciler.run_with_advisory_lock") as lock:
        reconciler.run_discovery_reconciliation()
        lock.assert_called_once()
        assert lock.call_args.args[0] == "discovery_reconciler"
        assert "job_fn" in lock.call_args.kwargs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_discovery_reconciler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.discovery_reconciler'`.

- [ ] **Step 3: Write `discovery_reconciler.py`**

```python
"""Self-healing reconciliation for discovery readiness (Phase 2).

Runs on a schedule (wired into APScheduler in main.py). Class-1 capabilities
(nmap_present, nmap_raw) are healed unconditionally on drift — no user
consent needed, matching Phase 1's own "should just always be true"
philosophy. Class-2 (LAN discovery) converges actual state toward the
persisted lan_discovery_desired setting, which only the user's explicit
toggle changes — the reconciler never enables LAN discovery on its own
initiative, only maintains or reverts what was already approved.

Per-capability failure counters are in-memory and reset on process restart;
this is a deliberate simplification (a missed backoff window after a
restart just means one extra retry at normal cadence, never incorrect
behavior).
"""

import logging
import time

from app.core.constants import (
    DISCOVERY_RECONCILE_BACKOFF_MINUTES,
    DISCOVERY_RECONCILE_FAILURE_THRESHOLD,
    DISCOVERY_RECONCILE_INTERVAL_MINUTES,
)
from app.core.job_lock import run_with_advisory_lock
from app.core.worker_audit import log_worker_audit
from app.db.session import SessionLocal
from app.services import helper_client
from app.services.discovery_readiness import CapState, get_discovery_readiness
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger(__name__)

_CLASS1_ACTIONS = {
    "nmap_present": "ensure_nmap",
    "nmap_raw": "grant_nmap_caps",
}

# capability_key -> {"failures": int, "next_attempt": float (time.monotonic())}
_STATE: dict[str, dict] = {}


def reset_reconciler_state_for_tests() -> None:
    _STATE.clear()


def _due(key: str) -> bool:
    state = _STATE.get(key)
    if state is None:
        return True
    return time.monotonic() >= state["next_attempt"]


def _record(key: str, *, success: bool) -> None:
    state = _STATE.setdefault(key, {"failures": 0, "next_attempt": 0.0})
    if success:
        state["failures"] = 0
        state["next_attempt"] = time.monotonic() + DISCOVERY_RECONCILE_INTERVAL_MINUTES * 60
    else:
        state["failures"] += 1
        interval = (
            DISCOVERY_RECONCILE_BACKOFF_MINUTES
            if state["failures"] >= DISCOVERY_RECONCILE_FAILURE_THRESHOLD
            else DISCOVERY_RECONCILE_INTERVAL_MINUTES
        )
        state["next_attempt"] = time.monotonic() + interval * 60


def _attempt_heal(key: str, action_name: str, action_fn) -> None:
    try:
        action_fn()
        _record(key, success=True)
        log_worker_audit(
            action=f"discovery_auto_heal_{action_name}",
            entity_type="discovery_capability",
            details=f"capability={key}",
            severity="info",
            worker_name="discovery_reconciler",
        )
    except Exception as exc:
        _record(key, success=False)
        log_worker_audit(
            action=f"discovery_auto_heal_{action_name}_failed",
            entity_type="discovery_capability",
            details=f"capability={key} error={exc}",
            severity="warn",
            worker_name="discovery_reconciler",
        )


def _reconcile_class1() -> None:
    if not helper_client.helper_installed():
        return
    caps_by_key = {c.key: c for c in get_discovery_readiness()}
    for key, action_name in _CLASS1_ACTIONS.items():
        cap = caps_by_key.get(key)
        if cap is None or cap.state != CapState.AUTO_FIXABLE:
            continue
        if not _due(key):
            continue
        action_fn = getattr(helper_client, action_name)
        _attempt_heal(key, action_name, action_fn)


def _reconcile_class2(db) -> None:
    if not helper_client.helper_installed():
        return
    settings = get_or_create_settings(db)
    desired = bool(getattr(settings, "lan_discovery_desired", False))
    caps_by_key = {c.key: c for c in get_discovery_readiness()}
    arp = caps_by_key.get("arp_l2")
    actual_on = arp is not None and arp.state == CapState.READY

    key = "lan_discovery"
    if desired and not actual_on:
        if _due(key):
            _attempt_heal(key, "enable_lan_discovery", helper_client.enable_lan_discovery)
    elif not desired and actual_on:
        if _due(key):
            _attempt_heal(key, "disable_lan_discovery", helper_client.disable_lan_discovery)


def _reconcile_once() -> None:
    db = SessionLocal()
    try:
        _reconcile_class1()
        _reconcile_class2(db)
    except Exception:
        logger.exception("discovery reconciliation pass failed")
    finally:
        db.close()


def run_discovery_reconciliation() -> None:
    """APScheduler entry point. Guarded by a Postgres advisory lock so only
    one backend replica reconciles at a time — required because
    enable/disable_lan_discovery recreate the container and must never run
    concurrently from two processes."""
    run_with_advisory_lock("discovery_reconciler", job_fn=_reconcile_once)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && python -m pytest tests/test_discovery_reconciler.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/discovery_reconciler.py apps/backend/tests/test_discovery_reconciler.py
git commit -m "feat(discovery): self-healing reconciliation loop (Class-1 auto-heal + Class-2 convergence)"
```

---

### Task 12: Wire `run_discovery_reconciliation` into the APScheduler startup

**Files:**
- Modify: `apps/backend/src/app/main.py:886-901` (the privacy-periodic job registration block)

**Interfaces:** none new — calls `discovery_reconciler.run_discovery_reconciliation` (Task 11) and `DISCOVERY_RECONCILE_INTERVAL_MINUTES` (Task 10).

- [ ] **Step 1: Add the job registration**

In `apps/backend/src/app/main.py`, right after the existing privacy-periodic block (which ends at line 901 with the closing `)` of its `scheduler.add_job(...)` call), add:

```python
    # Discovery-readiness Phase 2 — self-healing reconciliation. Always
    # scheduled; the job itself no-ops when cb-helperd isn't installed, so
    # the in-app LAN-discovery toggle applies without a restart once it is.
    from app.core.constants import DISCOVERY_RECONCILE_INTERVAL_MINUTES
    from app.services.discovery_reconciler import run_discovery_reconciliation

    scheduler.add_job(
        run_discovery_reconciliation,
        trigger=IntervalTrigger(minutes=DISCOVERY_RECONCILE_INTERVAL_MINUTES),
        id="discovery_reconciler",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )
```

`IntervalTrigger` is already imported earlier in the same function (line 860); no new import needed if this block is placed after that point (it is, since it follows the privacy-periodic block at line 894 which already uses `IntervalTrigger`).

- [ ] **Step 2: Verify the app still starts cleanly**

Run: `cd apps/backend && python -c "import ast; ast.parse(open('src/app/main.py').read())" && echo "syntax OK"`
Expected: `syntax OK`. (Full startup requires a live Postgres/Redis/NATS stack per `docs`/`backend-test-env-gotchas` — a syntax check is the fast local signal; the full stack boot is covered by Task 13's manual verification.)

- [ ] **Step 3: Commit**

```bash
git add apps/backend/src/app/main.py
git commit -m "feat(discovery): schedule discovery reconciler on the existing APScheduler"
```

---

### Task 13: Manual verification — compose override round-trip

Not automatable safely in this environment (recreating a container onto host networking needs a real Docker host and a real LAN). Documented here as the release-gate check before Phase 2 ships:

1. Deploy the Docker mono stack via `install.sh --docker` on a real Linux host (not Docker Desktop) with a LAN interface.
2. Confirm `systemctl status cb-helperd` is active and `/run/circuitbreaker/helper.sock` exists on the host.
3. `curl -s http://localhost/api/v1/discovery/readiness` — confirm `arp_l2`/`lan_adjacency` report `needs-helper-action`.
4. `PUT /api/v1/settings` with body `{"lan_discovery_desired": true}` (with a valid admin session — the settings router only exposes `PUT` for updates, not `PATCH`; see `apps/backend/tests/test_settings.py:8-9`) — wait up to `DISCOVERY_RECONCILE_INTERVAL_MINUTES` (15 min), or temporarily lower `DISCOVERY_RECONCILE_INTERVAL_MINUTES` for the test.
5. Confirm `docker inspect circuitbreaker --format '{{.HostConfig.NetworkMode}}'` reports `host`, and readiness now reports `arp_l2`/`lan_adjacency` as `ready`.
6. `docker compose -f docker-compose.yml up -d` (without `-f docker-compose.lan-discovery.yml`) to simulate accidental drift — confirm the reconciler re-applies the override on its next pass and `network_mode` returns to `host` without any user action.
7. Set `lan_discovery_desired` back to `false` — confirm the override is removed and `network_mode` reverts to the default (bridge).
8. Check `GET /api/v1/admin/audit` (or the equivalent audit log view) for `discovery_auto_heal_*` entries corresponding to each step above.

No code changes in this task — it's a checklist, not a step to commit.

---

## Plan Self-Review Notes

- **Spec coverage:** every component in `specs/2026-07-15-discovery-readiness-phase2-helper-design.md` maps to a task — `cb_helperd.py` (Tasks 1-4), `cb-helperd.service` (Task 5), `lan_discovery_desired` setting (Task 6), `helper_client.py` (Task 7), the compose bind mount (Task 8), installer wiring (Task 9), and `discovery_reconciler.py` + scheduling (Tasks 10-12). The spec's "extend `discovery_readiness.py` with auto-heal metadata" open item is deliberately **not** implemented here — it's UI-adjacent (last-healed timestamps are only useful once Phase 3 has somewhere to show them) and the audit log already captures every auto-heal attempt, so adding it now would be speculative surface with no consumer yet.
- **Type/name consistency checked:** `helper_client`'s five wrapper names match `cb_helperd.ALLOWED_ACTIONS` exactly; `discovery_reconciler._CLASS1_ACTIONS` values (`"ensure_nmap"`, `"grant_nmap_caps"`) match `helper_client` function names via `getattr`; `CapState`/`Capability` are imported, never redefined; `lan_discovery_desired` is spelled identically across the migration, model, both schemas, the default dict, and the reconciler.
- **Open item resolved during planning:** the spec's deferred question about a distinct `system:reconciler` audit actor type is resolved by reusing the existing `app.core.worker_audit.log_worker_audit` convention (`worker_name="discovery_reconciler"`) — no schema change needed, it already exists for exactly this purpose.
