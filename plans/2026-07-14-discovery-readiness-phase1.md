# Discovery Readiness — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make network discovery reliable and never fail silently — detect discovery capabilities, block/​warn loudly when they're missing, auto-provision the nmap binary + raw-socket privilege on every deploy path, and fix the ambient-capability detection bug.

**Architecture:** A backend `discovery_readiness` service computes a shared capability model (`nmap_present`, `nmap_raw`, `arp_l2`, `lan_adjacency`), each resolving to one of four states. The scan runner consults it to emit blocking or warning scan events instead of silent empty results. Startup logs the model loudly. Deploy-path provisioning (Docker entrypoint, `setup.sh`, `PKGBUILD`, `make dev`) guarantees the nmap binary and `CAP_NET_RAW` reach the discovery process.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, pytest (`asyncio_mode = "auto"`), python-nmap, scapy, supervisord, Debian/apt (mono image), systemd (bare-metal).

**Scope:** This is **Phase 1 of 3**. It delivers reliability + fail-loud + Class-1 auto-provisioning. Phase 2 adds the `cb-helperd` privileged host helper and `helper_client`. Phase 3 adds the in-app Readiness panel + LAN-discovery toggle. `arp_l2` / `lan_adjacency` are *detected and reported* here but their remediation (`needs-helper-action`) is wired in Phase 2.

**Spec:** `specs/2026-07-14-discovery-readiness-capability-broker-design.md`

## Global Constraints

- Backend source lives under `apps/backend/src/app/`; tests under `apps/backend/tests/`.
- Tests use `pytest` with `asyncio_mode = "auto"` — async tests need **no** `@pytest.mark.asyncio` decorator.
- The capability **state** vocabulary is exactly these four strings, used verbatim everywhere: `ready`, `auto-fixable`, `needs-helper-action`, `unavailable-on-platform`.
- The capability **key** vocabulary is exactly: `nmap_present`, `nmap_raw`, `arp_l2`, `lan_adjacency`.
- Never pass unvalidated strings to a subprocess; existing `validate_nmap_arguments` / `_validate_cidr` guards stay in force.
- The mono container runs `supervisord` as user `breaker` (uid 1000); the discovery scan executes inside the `workers` process (`--type=0`), not `backend-api`.
- New privileged provisioning must not broaden container capabilities beyond the existing `CAP_NET_RAW`, and must respect `no-new-privileges:true` + read-only rootfs.
- Discovery API routes require `require_role("admin")` and live in `apps/backend/src/app/api/discovery.py` under `router = APIRouter(tags=["discovery"], dependencies=[require_scope("read", "*")])`.

## File Structure

- **Create** `apps/backend/src/app/services/discovery_readiness.py` — capability model + detection (one responsibility: "what can discovery do right now?").
- **Create** `apps/backend/tests/test_discovery_readiness.py` — unit tests for the model/detection.
- **Create** `apps/backend/tests/test_discovery_failloud.py` — tests for the pre-scan gate + degraded warning.
- **Modify** `apps/backend/src/app/services/discovery_probes.py` — add `nmap_binary_present()`; fix `_nmap_os_capable()` ambient-cap detection.
- **Modify** `apps/backend/src/app/services/discovery_service.py` — pre-scan gate + degraded warning event.
- **Modify** `apps/backend/src/app/api/discovery.py` — `GET /discovery/readiness` endpoint.
- **Modify** `apps/backend/src/app/main.py` (or existing startup hook) — startup readiness logging.
- **Modify** `Makefile` — `make dev` ensures nmap present.
- **Modify** `deploy/setup.sh` — `setcap cap_net_raw` on nmap.
- **Modify** `PKGBUILD` — add `nmap` to `depends`.
- **Modify** `docker/supervisord.mono.conf` + `docker/entrypoint-mono.sh` — ambient-cap launcher for the discovery worker (after the spike task confirms mechanism).

---

### Task 1: `nmap_binary_present()` probe

**Files:**
- Modify: `apps/backend/src/app/services/discovery_probes.py`
- Test: `apps/backend/tests/test_discovery_readiness.py`

**Interfaces:**
- Produces: `nmap_binary_present() -> bool` (True iff the `nmap` executable is on PATH).

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_discovery_readiness.py
from unittest.mock import patch


def test_nmap_binary_present_true_when_on_path():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value="/usr/bin/nmap"):
        assert nmap_binary_present() is True


def test_nmap_binary_present_false_when_missing():
    from app.services.discovery_probes import nmap_binary_present

    with patch("shutil.which", return_value=None):
        assert nmap_binary_present() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -v`
Expected: FAIL — `ImportError: cannot import name 'nmap_binary_present'`.

- [ ] **Step 3: Write minimal implementation**

Add to `discovery_probes.py` (near the other capability helpers):

```python
def nmap_binary_present() -> bool:
    """True iff the nmap executable is available on PATH.

    python-nmap imports successfully even when the nmap binary is absent, so
    this is the authoritative presence check for discovery.
    """
    import shutil

    return shutil.which("nmap") is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/discovery_probes.py apps/backend/tests/test_discovery_readiness.py
git commit -m "feat(discovery): add nmap_binary_present() probe"
```

---

### Task 2: Fix `_nmap_os_capable()` ambient-capability detection

**Files:**
- Modify: `apps/backend/src/app/services/discovery_probes.py:140-160`
- Test: `apps/backend/tests/test_discovery_readiness.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `_nmap_os_capable()` now also returns True when `CAP_NET_RAW` is in the process **ambient** set (bit 13), fixing the needless `-sT` downgrade on the working bare-metal path.

CAP_NET_RAW is capability number 13, so its bit mask is `1 << 13 == 0x2000`.

- [ ] **Step 1: Write the failing test**

```python
def test_nmap_os_capable_true_with_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    # CapAmb with bit 13 set → 0x0000000000002000
    proc_status = "Name:\tpython\nCapAmb:\t0000000000002000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is True


def test_nmap_os_capable_false_without_ambient_net_raw():
    from app.services.discovery_probes import _has_ambient_net_raw

    proc_status = "Name:\tpython\nCapAmb:\t0000000000000000\n"
    with patch("builtins.open", _mock_open_text(proc_status)):
        assert _has_ambient_net_raw() is False


def _mock_open_text(text):
    from unittest.mock import mock_open

    return mock_open(read_data=text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k ambient -v`
Expected: FAIL — `ImportError: cannot import name '_has_ambient_net_raw'`.

- [ ] **Step 3: Write minimal implementation**

Add helper and use it in `_nmap_os_capable()`:

```python
_CAP_NET_RAW_BIT = 1 << 13  # CAP_NET_RAW is capability number 13


def _has_ambient_net_raw() -> bool:
    """True iff CAP_NET_RAW is in this process's ambient capability set.

    Ambient caps are inherited across execve, so an nmap child launched by an
    ambient-capable parent can perform raw scans without a file capability.
    """
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("CapAmb:"):
                    return bool(int(line.split()[1], 16) & _CAP_NET_RAW_BIT)
    except Exception:
        return False
    return False
```

Then modify `_nmap_os_capable()` — add the ambient check before the `getcap` fallback:

```python
def _nmap_os_capable() -> bool:
    import os
    import shutil
    import subprocess

    if os.geteuid() == 0:
        return True
    if _has_ambient_net_raw():  # ambient caps propagate to the nmap child
        return True
    nmap_path = shutil.which("nmap")
    if not nmap_path:
        return False
    try:
        r = subprocess.run(["getcap", nmap_path], capture_output=True, text=True, timeout=2)
        return "cap_net_raw" in r.stdout
    except Exception:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k ambient -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/discovery_probes.py apps/backend/tests/test_discovery_readiness.py
git commit -m "fix(discovery): recognize ambient CAP_NET_RAW so nmap OS detection isn't needlessly downgraded"
```

---

### Task 3: Capability model + readiness service

**Files:**
- Create: `apps/backend/src/app/services/discovery_readiness.py`
- Test: `apps/backend/tests/test_discovery_readiness.py`

**Interfaces:**
- Consumes: `nmap_binary_present()`, `_nmap_os_capable()`, `_arp_available()` from `discovery_probes`.
- Produces:
  - `CapState` (str Enum): `READY="ready"`, `AUTO_FIXABLE="auto-fixable"`, `NEEDS_HELPER_ACTION="needs-helper-action"`, `UNAVAILABLE_ON_PLATFORM="unavailable-on-platform"`.
  - `@dataclass Capability` with fields `key: str`, `title: str`, `state: CapState`, `explanation: str`, `reason_code: str`.
  - `get_discovery_readiness() -> list[Capability]` — one entry per key in order `nmap_present`, `nmap_raw`, `arp_l2`, `lan_adjacency`.
  - `detect_lan_adjacency() -> bool` — best-effort "am I directly on a LAN, not a docker bridge".

- [ ] **Step 1: Write the failing test**

```python
def test_readiness_all_ready_when_capable():
    import app.services.discovery_readiness as r

    with patch.object(r, "nmap_binary_present", return_value=True), \
         patch.object(r, "_nmap_os_capable", return_value=True), \
         patch.object(r, "_arp_available", return_value=True), \
         patch.object(r, "detect_lan_adjacency", return_value=True):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert [c.key for c in r.get_discovery_readiness.__wrapped__()] if False else True
    assert caps["nmap_present"].state == r.CapState.READY
    assert caps["nmap_raw"].state == r.CapState.READY
    assert caps["arp_l2"].state == r.CapState.READY
    assert caps["lan_adjacency"].state == r.CapState.READY


def test_readiness_nmap_missing_is_auto_fixable():
    import app.services.discovery_readiness as r

    with patch.object(r, "nmap_binary_present", return_value=False), \
         patch.object(r, "_nmap_os_capable", return_value=False), \
         patch.object(r, "_arp_available", return_value=False), \
         patch.object(r, "detect_lan_adjacency", return_value=True):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["nmap_present"].state == r.CapState.AUTO_FIXABLE
    assert caps["nmap_present"].explanation  # non-empty human text


def test_readiness_arp_needs_helper_when_no_adjacency():
    import app.services.discovery_readiness as r

    with patch.object(r, "nmap_binary_present", return_value=True), \
         patch.object(r, "_nmap_os_capable", return_value=True), \
         patch.object(r, "_arp_available", return_value=False), \
         patch.object(r, "detect_lan_adjacency", return_value=False):
        caps = {c.key: c for c in r.get_discovery_readiness()}

    assert caps["arp_l2"].state == r.CapState.NEEDS_HELPER_ACTION
    assert caps["lan_adjacency"].state == r.CapState.NEEDS_HELPER_ACTION
```

(Remove the throwaway `__wrapped__` assertion line before finalizing — it's only there to show the key-order expectation; replace with `assert [c.key for c in r.get_discovery_readiness()] == ["nmap_present", "nmap_raw", "arp_l2", "lan_adjacency"]` guarded by the same patches.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k readiness -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.discovery_readiness'`.

- [ ] **Step 3: Write minimal implementation**

```python
# apps/backend/src/app/services/discovery_readiness.py
"""Discovery capability model + runtime detection.

Answers "what can discovery do right now?" as a small, explicit set of
capabilities, each in exactly one state. Shared verbatim by the scan runner,
the readiness API, and (Phase 3) the in-app Readiness panel.
"""

import ipaddress
import logging
from dataclasses import dataclass
from enum import Enum

from app.services.discovery_probes import (
    _arp_available,
    _nmap_os_capable,
    nmap_binary_present,
)

logger = logging.getLogger(__name__)


class CapState(str, Enum):
    READY = "ready"
    AUTO_FIXABLE = "auto-fixable"
    NEEDS_HELPER_ACTION = "needs-helper-action"
    UNAVAILABLE_ON_PLATFORM = "unavailable-on-platform"


@dataclass
class Capability:
    key: str
    title: str
    state: CapState
    explanation: str
    reason_code: str


# Docker default bridge ranges (docker0 + user-defined bridges live in 172.16/12).
_DOCKER_BRIDGE_NET = ipaddress.ip_network("172.16.0.0/12")


def detect_lan_adjacency() -> bool:
    """Best-effort: True if this process is directly on a LAN, not a docker bridge.

    Heuristic: if the only RFC1918 interface addresses fall inside the docker
    bridge range (172.16/12) AND /.dockerenv exists, we're almost certainly a
    bridged container with no L2 reach to the user's LAN. Any interface on a
    192.168/16 or 10/8 address is treated as real LAN adjacency.
    """
    import os
    import socket

    in_container = os.path.exists("/.dockerenv")
    addrs: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addrs.append(info[4][0])
    except Exception:
        pass
    for a in addrs:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_loopback or not ip.is_private:
            continue
        if ip not in _DOCKER_BRIDGE_NET:
            return True  # on a real LAN (192.168/16 or 10/8)
    # No non-bridge private address found.
    return not in_container


def get_discovery_readiness() -> list[Capability]:
    has_nmap = nmap_binary_present()
    has_raw = _nmap_os_capable()
    has_arp = _arp_available()
    has_lan = detect_lan_adjacency()

    nmap_present = Capability(
        key="nmap_present",
        title="Nmap scanner",
        state=CapState.READY if has_nmap else CapState.AUTO_FIXABLE,
        explanation=(
            "The nmap scanner is installed and available."
            if has_nmap
            else "The nmap binary is missing — discovery cannot actively scan. "
            "It is installed automatically on next start/install."
        ),
        reason_code="nmap_ok" if has_nmap else "nmap_binary_missing",
    )
    nmap_raw = Capability(
        key="nmap_raw",
        title="Fast host discovery & OS detection",
        state=CapState.READY if has_raw else CapState.AUTO_FIXABLE,
        explanation=(
            "Raw-socket privilege is available; ICMP/SYN sweeps and OS "
            "detection are enabled."
            if has_raw
            else "Raw-socket privilege (CAP_NET_RAW) is missing; nmap falls back "
            "to slower TCP-connect discovery. Granted automatically at startup."
        ),
        reason_code="raw_ok" if has_raw else "raw_priv_missing",
    )
    arp_l2 = Capability(
        key="arp_l2",
        title="ARP / MAC address resolution",
        state=CapState.READY
        if has_arp
        else (
            CapState.NEEDS_HELPER_ACTION
            if not has_lan or has_raw
            else CapState.NEEDS_HELPER_ACTION
        ),
        explanation=(
            "ARP scanning is available; MAC addresses are resolved for LAN hosts."
            if has_arp
            else "ARP scanning is unavailable — MAC resolution and the most "
            "reliable LAN sweep are off. Enable LAN discovery in Discovery Settings."
        ),
        reason_code="arp_ok" if has_arp else "arp_unavailable",
    )
    lan_adjacency = Capability(
        key="lan_adjacency",
        title="Direct LAN reachability",
        state=CapState.READY if has_lan else CapState.NEEDS_HELPER_ACTION,
        explanation=(
            "This instance is directly on your LAN."
            if has_lan
            else "This instance appears to be on a Docker bridge, not your LAN, "
            "so Layer-2 discovery (ARP) can't reach hosts. Enable LAN discovery "
            "in Discovery Settings."
        ),
        reason_code="lan_ok" if has_lan else "bridged_no_l2",
    )
    return [nmap_present, nmap_raw, arp_l2, lan_adjacency]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -v`
Expected: PASS (all readiness tests green).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/discovery_readiness.py apps/backend/tests/test_discovery_readiness.py
git commit -m "feat(discovery): capability model + readiness detection service"
```

---

### Task 4: `GET /api/v1/discovery/readiness` endpoint

**Files:**
- Modify: `apps/backend/src/app/api/discovery.py`
- Test: `apps/backend/tests/test_discovery_readiness.py`

**Interfaces:**
- Consumes: `get_discovery_readiness()`, `Capability`, `CapState`.
- Produces: `GET /api/v1/discovery/readiness` → `{"capabilities": [{"key","title","state","explanation","reason_code"}, ...]}`.

- [ ] **Step 1: Write the failing test**

```python
def test_readiness_endpoint_returns_capabilities(client, admin_auth_headers):
    resp = client.get("/api/v1/discovery/readiness", headers=admin_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    keys = [c["key"] for c in body["capabilities"]]
    assert keys == ["nmap_present", "nmap_raw", "arp_l2", "lan_adjacency"]
    for c in body["capabilities"]:
        assert c["state"] in {
            "ready", "auto-fixable", "needs-helper-action", "unavailable-on-platform",
        }
        assert c["explanation"]
```

(If the test suite's fixtures for an authenticated admin client are named differently, match the existing convention in `apps/backend/tests/test_discovery.py` / `conftest.py`; reuse the same admin-auth fixture those tests use.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k endpoint -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Write minimal implementation**

Add to `apps/backend/src/app/api/discovery.py`:

```python
@router.get("/readiness")
def get_readiness(user: User = require_role("admin")) -> dict:
    from app.services.discovery_readiness import get_discovery_readiness

    return {
        "capabilities": [
            {
                "key": c.key,
                "title": c.title,
                "state": c.state.value,
                "explanation": c.explanation,
                "reason_code": c.reason_code,
            }
            for c in get_discovery_readiness()
        ]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k endpoint -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/api/discovery.py apps/backend/tests/test_discovery_readiness.py
git commit -m "feat(discovery): GET /discovery/readiness endpoint"
```

---

### Task 5: Loud startup readiness logging

**Files:**
- Modify: `apps/backend/src/app/main.py` (startup/lifespan hook)
- Test: `apps/backend/tests/test_discovery_readiness.py`

**Interfaces:**
- Consumes: `get_discovery_readiness()`.
- Produces: `log_discovery_readiness_at_startup() -> None` — logs WARNING for each non-`ready` capability, INFO when all ready.

- [ ] **Step 1: Write the failing test**

```python
def test_startup_logging_warns_on_degraded(caplog):
    import logging
    import app.services.discovery_readiness as r

    with patch.object(r, "nmap_binary_present", return_value=False), \
         patch.object(r, "_nmap_os_capable", return_value=False), \
         patch.object(r, "_arp_available", return_value=False), \
         patch.object(r, "detect_lan_adjacency", return_value=True), \
         caplog.at_level(logging.WARNING):
        r.log_discovery_readiness_at_startup()

    assert any("nmap" in rec.message.lower() for rec in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k startup -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'log_discovery_readiness_at_startup'`.

- [ ] **Step 3: Write minimal implementation**

Add to `discovery_readiness.py`:

```python
def log_discovery_readiness_at_startup() -> None:
    """Emit a loud log line per non-ready capability so degraded discovery is
    visible at boot, never discovered only at scan time."""
    caps = get_discovery_readiness()
    degraded = [c for c in caps if c.state != CapState.READY]
    if not degraded:
        logger.info("Discovery readiness: all capabilities ready.")
        return
    for c in degraded:
        logger.warning(
            "Discovery readiness: %s is %s — %s",
            c.key,
            c.state.value,
            c.explanation,
        )
```

Then call it from the FastAPI startup/lifespan in `main.py` (match the existing startup pattern — inside the existing lifespan/`@app.on_event("startup")` handler):

```python
    from app.services.discovery_readiness import log_discovery_readiness_at_startup
    log_discovery_readiness_at_startup()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_readiness.py -k startup -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/src/app/services/discovery_readiness.py apps/backend/src/app/main.py apps/backend/tests/test_discovery_readiness.py
git commit -m "feat(discovery): loud startup logging of degraded discovery capabilities"
```

---

### Task 6: Fail-loud pre-scan gate + degraded warning

**Files:**
- Modify: `apps/backend/src/app/services/discovery_service.py` (nmap phase, near `discovery_probes.py:1112` call site and the `_run_scan_job` orchestration)
- Test: `apps/backend/tests/test_discovery_failloud.py`

**Interfaces:**
- Consumes: `get_discovery_readiness()`, `CapState`, `_requires_nmap()`, `_log_scan_event(job_id, level, message, phase, details)`.
- Produces: when a scan requires nmap but `nmap_present` != `ready`, the job emits a blocking ERROR event `"nmap unavailable — discovery cannot run. Enable it in Discovery Settings."` and completes with status `failed`; when `arp_l2` != `ready` on an nmap scan, emit a WARNING event and continue.

- [ ] **Step 1: Write the failing test**

```python
# apps/backend/tests/test_discovery_failloud.py
from unittest.mock import patch

import app.services.discovery_service as ds
from app.services.discovery_readiness import CapState, Capability


def _cap(key, state):
    return Capability(key=key, title=key, state=state, explanation="x", reason_code="x")


def test_scan_blocks_loudly_when_nmap_absent():
    caps = [
        _cap("nmap_present", CapState.AUTO_FIXABLE),
        _cap("nmap_raw", CapState.AUTO_FIXABLE),
        _cap("arp_l2", CapState.NEEDS_HELPER_ACTION),
        _cap("lan_adjacency", CapState.READY),
    ]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["nmap"])
    assert blocked is True
    assert "nmap" in reason.lower()


def test_scan_allowed_when_nmap_ready():
    caps = [
        _cap("nmap_present", CapState.READY),
        _cap("nmap_raw", CapState.READY),
        _cap("arp_l2", CapState.READY),
        _cap("lan_adjacency", CapState.READY),
    ]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["nmap"])
    assert blocked is False
    assert reason == ""


def test_gate_ignored_for_non_nmap_scan():
    caps = [_cap("nmap_present", CapState.AUTO_FIXABLE)]
    with patch.object(ds, "get_discovery_readiness", return_value=caps):
        blocked, reason = ds._scan_capability_gate(scan_types=["docker"])
    assert blocked is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && python -m pytest tests/test_discovery_failloud.py -v`
Expected: FAIL — `AttributeError: module 'app.services.discovery_service' has no attribute '_scan_capability_gate'`.

- [ ] **Step 3: Write minimal implementation**

Add the pure gate helper to `discovery_service.py` (import at top of module: `from app.services.discovery_readiness import get_discovery_readiness, CapState`):

```python
def _scan_capability_gate(scan_types: list[str] | None) -> tuple[bool, str]:
    """Return (blocked, reason). Blocks an nmap-requiring scan when the nmap
    binary isn't ready, so discovery fails loudly instead of returning empty."""
    if not _requires_nmap(scan_types):
        return False, ""
    caps = {c.key: c for c in get_discovery_readiness()}
    nmap_cap = caps.get("nmap_present")
    if nmap_cap is not None and nmap_cap.state != CapState.READY:
        return True, (
            "nmap unavailable — discovery cannot run. "
            "Enable it in Discovery Settings."
        )
    return False, ""
```

Wire it into the scan runner (in the async `_run_scan_job` before the network-discovery phase, alongside the existing readiness of `scan_types`): if blocked, emit and finalize as failed.

```python
        blocked, block_reason = _scan_capability_gate(scan_types)
        if blocked:
            await _log_scan_event(job_id, "ERROR", block_reason, "nmap")
            await loop.run_in_executor(None, _scan_finalize, job_id, {}, "failed", False)
            await _emit_ws_event(
                "job_update", {"job": {"id": job_id, "status": "failed"}}
            )
            return
        # Degraded (usable) capabilities → warn, don't block.
        _degraded = [
            c for c in get_discovery_readiness()
            if c.key == "arp_l2" and c.state != CapState.READY
        ]
        if _degraded and _requires_nmap(scan_types):
            await _log_scan_event(
                job_id, "WARNING",
                _degraded[0].explanation, "arp",
            )
```

(Match `_scan_finalize`'s existing signature — confirm arg order against its definition in the same file before wiring.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && python -m pytest tests/test_discovery_failloud.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full discovery suite for regressions**

Run: `cd apps/backend && python -m pytest tests/test_discovery.py tests/test_discovery_readiness.py tests/test_discovery_failloud.py -v`
Expected: PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add apps/backend/src/app/services/discovery_service.py apps/backend/tests/test_discovery_failloud.py
git commit -m "feat(discovery): fail loudly when nmap is unavailable; warn on degraded ARP"
```

---

### Task 7: Guarantee nmap in dev + packaging

**Files:**
- Modify: `Makefile` (the `deps-up` / `backend` prerequisite path, or a new `ensure-nmap` target)
- Modify: `deploy/setup.sh` (near the existing nmap install at `setup.sh:1131` and the setcap block at `setup.sh:895-904`)
- Modify: `PKGBUILD:9`

**Interfaces:** none (build/deploy only).

- [ ] **Step 1: Add an `ensure-nmap` guard to `make dev`**

In `Makefile`, add a target and make `dev` depend on it:

```make
ensure-nmap:  ## Fail early if the nmap binary is missing (discovery needs it)
	@command -v nmap >/dev/null 2>&1 || { \
	  echo "ERROR: nmap not found. Install it (Fedora: sudo dnf install nmap; Debian: sudo apt install nmap) then re-run."; \
	  exit 1; }
```

Change the `dev` target line from `dev: deps-up stop` to `dev: ensure-nmap deps-up stop`.

- [ ] **Step 2: Verify the guard fires**

Run: `make ensure-nmap`
Expected (nmap absent): prints the ERROR line and exits non-zero. (nmap present): silent success.

- [ ] **Step 3: Add `setcap` on nmap in bare-metal install**

In `deploy/setup.sh`, in the capability-granting block (`cb_step "Granting NET_RAW capability"`), after the existing `setcap` on the circuit-breaker binary, add:

```bash
  if command -v nmap &>/dev/null && command -v setcap &>/dev/null; then
    if setcap cap_net_raw+eip "$(command -v nmap)" >> "$LOG_FILE" 2>&1; then
      cb_ok "NET_RAW capability granted to nmap"
    else
      cb_warn "setcap on nmap failed — active host discovery may be degraded"
    fi
  fi
```

- [ ] **Step 4: Add nmap to the Arch package deps**

In `PKGBUILD`, change:

```
depends=('postgresql' 'redis' 'nginx')
```
to:
```
depends=('postgresql' 'redis' 'nginx' 'nmap')
```

- [ ] **Step 5: Lint the shell change**

Run: `shellcheck deploy/setup.sh || true` (review new lines only; pre-existing warnings are out of scope).
Expected: no new errors introduced by the added block.

- [ ] **Step 6: Commit**

```bash
git add Makefile deploy/setup.sh PKGBUILD
git commit -m "build(discovery): guarantee nmap binary + setcap across dev, bare-metal, and Arch packaging"
```

---

### Task 8: Docker ambient-capability provisioning (spike → implement)

**Files:**
- Modify: `docker/supervisord.mono.conf` (`[program:workers]` block, lines ~103-116)
- Modify: `docker/entrypoint-mono.sh` (if the spike shows supervisord must not drop to `breaker` globally)
- Modify: `Dockerfile.mono` (ensure `util-linux` `setpriv` is present — it ships in Debian `util-linux`, already installed; verify)

**Interfaces:** none (runtime provisioning). Verified by the readiness service reporting `nmap_raw = ready` inside the container.

> **Why a spike:** `supervisord` runs as `breaker` (`supervisord.mono.conf:2`), so it cannot raise a child's ambient caps (needs `CAP_SETPCAP` + the cap in its permitted/inheritable sets). The mechanism must be validated empirically against `no-new-privileges:true` before committing to it.

- [ ] **Step 1: Spike — determine the working mechanism**

Build and run the mono image, then probe from inside the running container:

```bash
docker compose up -d --build
# A) Does the container hold NET_RAW in its bounding set?
docker compose exec circuitbreaker sh -c 'grep Cap /proc/1/status'
# B) Can a breaker-owned process open a raw socket today? (expected: no)
docker compose exec -u breaker circuitbreaker python3 -c \
  "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP); print('RAW OK')" || echo "RAW DENIED (expected pre-fix)"
# C) Is setpriv available?
docker compose exec circuitbreaker sh -c 'command -v setpriv && setpriv --help >/dev/null && echo SETPRIV_OK'
```

Record which of these two mechanisms works under `no-new-privileges:true`:
- **Mechanism 1 (preferred):** run the `workers` program under a launcher that starts as root and drops with ambient caps. Requires `[supervisord] user` to remain able to spawn a root program for `workers` (set `user=root` on that program only) and the launcher: `setpriv --reuid breaker --regid breaker --init-groups --ambient-caps +net_raw --inh-caps +net_raw ...`.
- **Mechanism 2 (fallback):** `setcap cap_net_raw+eip` on `/usr/bin/nmap` in the Dockerfile. NOTE: file caps are **neutralized by `no-new-privileges`**, so this only helps if the discovery worker path doesn't rely on privilege elevation via execve — validate B/C above before choosing it.

- [ ] **Step 2: Write the failing verification (container-level)**

Create `TESTING/verify-nmap-raw-in-container.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
# Passes only when the discovery worker context can open a raw socket.
docker compose exec -u breaker circuitbreaker \
  /usr/bin/setpriv --reuid breaker --regid breaker --init-groups \
    --ambient-caps +net_raw --inh-caps +net_raw \
    python3 -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP); print('RAW OK')"
```

Run it before the fix.
Expected: FAIL (raw socket denied) — confirming the gap.

- [ ] **Step 3: Implement the chosen mechanism (Mechanism 1)**

In `docker/supervisord.mono.conf`, change the `[program:workers]` block: remove `user=breaker` and set the command to launch via `setpriv`:

```ini
[program:workers]
priority=30
numprocs=7
process_name=worker-%(process_num)02d
command=/usr/bin/setpriv --reuid breaker --regid breaker --init-groups --ambient-caps +net_raw --inh-caps +net_raw /usr/bin/python -m app.workers.main --type=%(process_num)d
directory=/app/backend
autostart=true
autorestart=true
startsecs=5
stopwaitsecs=20
stdout_logfile=/data/worker_%(process_num)d.log
stderr_logfile=/data/worker_%(process_num)d_err.log
```

If the spike shows supervisord (running as `breaker`) cannot spawn this, set `[supervisord] user=root` and add `user=breaker` back to **every other** program block (postgres, pgbouncer, nats, redis, backend-api, nginx) so only `workers` retains the ambient-cap launcher. Document the choice inline.

- [ ] **Step 4: Rebuild and run the verification**

Run: `docker compose up -d --build && bash TESTING/verify-nmap-raw-in-container.sh`
Expected: prints `RAW OK`.

- [ ] **Step 5: Confirm readiness flips inside the container**

Run: `docker compose exec -u breaker circuitbreaker python3 -c "from app.services.discovery_readiness import get_discovery_readiness as g; print({c.key: c.state.value for c in g()})"`
Expected: `nmap_present` and `nmap_raw` both `ready`.

- [ ] **Step 6: Commit**

```bash
git add docker/supervisord.mono.conf docker/entrypoint-mono.sh Dockerfile.mono TESTING/verify-nmap-raw-in-container.sh
git commit -m "feat(discovery): grant CAP_NET_RAW to the discovery worker via ambient caps in the mono container"
```

---

## Self-Review

**Spec coverage (§ → task):**
- §2 Class-1 auto-provision → Tasks 7 (bare-metal/dev/Arch) + 8 (Docker).
- §2 detection-bug fix → Task 2.
- §3 readiness service + API → Tasks 3, 4.
- §3 startup logging → Task 5.
- §4 fail-loud scan integration → Task 6.
- §1 capability model → Task 3.
- Phase-2/3 items (`cb-helperd`, helper_client, in-app panel, `arp_l2`/`lan_adjacency` *remediation*) → intentionally deferred; this plan only *detects/reports* them.

**Placeholder scan:** Task 3's test contains one throwaway assertion line explicitly flagged for replacement (the `__wrapped__` line) with the concrete key-order assertion — the implementer replaces it as instructed. No other TBD/TODO/"handle edge cases" placeholders. Task 5 and Task 6 reference "the existing startup pattern" / "existing `_scan_finalize` signature" — these are real, in-repo anchors the implementer confirms, not invented interfaces.

**Type consistency:** `CapState` values and `Capability` fields are identical across Tasks 3–6. Capability keys use the same four strings throughout. `get_discovery_readiness()`, `nmap_binary_present()`, `_has_ambient_net_raw()`, `_scan_capability_gate()` names are consistent between definition and use.

**Known validation points (call out to implementer, not gaps):**
- Task 4 admin-auth fixture name must match `conftest.py`.
- Task 6 `_scan_finalize` / `_run_scan_job` exact insertion point and arg order confirmed against the live file.
- Task 8 mechanism confirmed by the Step 1 spike before the Step 3 edit.
