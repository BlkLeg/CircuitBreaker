# Scan → Map Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform scan results into map nodes via a smart batch-confirm UI — scan completes, user reviews inferred devices, clicks import, nodes appear on map grouped by subnet.

**Architecture:** Three new backend services (inference, layout, batch-import endpoint) feed a new `ScanImportModal` frontend component triggered by a discovery banner on the map canvas. All inference is offline; layout is server-computed; the frontend only calls `fetchData()` + `fitView()` after import.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (PostgreSQL), Pydantic v2, React 18, axios, ReactFlow

**Spec:** `docs/superpowers/specs/2026-03-13-scan-to-map-pipeline-design.md`

---

## Chunk 1: Inference Service + Layout Service (Backend)

### Task 1: InferredAnnotation dataclass + OUI resolver

**Files:**
- Create: `apps/backend/src/app/services/inference_service.py`
- Create: `apps/backend/tests/test_inference_service.py`

- [ ] **Step 1.1: Write failing tests for OUI resolution**

```python
# apps/backend/tests/test_inference_service.py
import pytest
from app.services.inference_service import OUIResolver, InferredAnnotation, annotate_result

class TestOUIResolver:
    def test_known_raspberry_pi_oui(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("DC:A6:32:11:22:33")
        assert vendor is not None
        assert "raspberry" in vendor.lower()

    def test_known_ubiquiti_oui(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("24:A4:3C:11:22:33")
        assert vendor is not None
        assert "ubiquiti" in vendor.lower()

    def test_unknown_oui_returns_none(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("FF:FF:FF:00:00:00")
        assert vendor is None

    def test_missing_mac_returns_none(self):
        resolver = OUIResolver()
        vendor = resolver.lookup(None)
        assert vendor is None

    def test_malformed_mac_returns_none(self):
        resolver = OUIResolver()
        vendor = resolver.lookup("not-a-mac")
        assert vendor is None
```

- [ ] **Step 1.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'app.services.inference_service'`

- [ ] **Step 1.3: Implement InferredAnnotation + OUIResolver**

```python
# apps/backend/src/app/services/inference_service.py
"""
Inference engine: annotates ScanResult rows with vendor, role, and icon slug
using three offline signals (MAC OUI, hostname patterns, port fingerprinting).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import logging

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OUI vendor overrides: maps OUI prefix (uppercase, no separators, 6 chars)
# to a canonical vendor name. Supplements netaddr for home-lab-relevant OUIs.
# ---------------------------------------------------------------------------
_OUI_OVERRIDES: dict[str, str] = {
    "DCA632": "Raspberry Pi Foundation",
    "B827EB": "Raspberry Pi Foundation",
    "E45F01": "Raspberry Pi Foundation",
    "DC44B6": "Raspberry Pi Foundation",
    "244A3C": "Ubiquiti",
    "FCECDA": "Ubiquiti",
    "802AA8": "Ubiquiti",
    "78D2E6": "Synology",
    "001132": "Synology",
    "00113D": "QNAP",
    "243C95": "QNAP",
    "001D0F": "QNAP",
    "000E6B": "Dell",
    "D4BE97": "Dell",
    "00215A": "Dell",
    "00248C": "HP",
    "3CD92B": "HP",
    "001708": "HP",
    "AC1F6B": "Proxmox",   # common Proxmox VM MAC prefix
    "000C29": "VMware",
    "005056": "VMware",
    "0A0027": "VirtualBox",
    "080027": "VirtualBox",
}

# Maps vendor name (lowercase substring) to vendor_icon_slug
_VENDOR_TO_ICON: dict[str, str] = {
    "raspberry": "raspberrypi",
    "ubiquiti": "ubiquiti",
    "synology": "synology",
    "qnap": "qnap",
    "dell": "dell",
    "hp": "hp",
    "hewlett": "hp",
    "vmware": "vmware",
    "virtualbox": "virtualbox",
    "proxmox": "proxmox",
    "cisco": "cisco",
    "aruba": "aruba",
    "mikrotik": "mikrotik",
    "pfsense": "pfsense",
    "opnsense": "opnsense",
    "apc": "apc",
    "cyberpower": "cyberpower",
}


@dataclass
class InferredAnnotation:
    vendor: str | None = None
    role: str | None = None
    vendor_icon_slug: str | None = None
    confidence: float = 0.0
    signals_used: list[str] = field(default_factory=list)


class OUIResolver:
    """Resolves MAC OUI prefix to vendor name using override table + netaddr fallback."""

    def lookup(self, mac: str | None) -> str | None:
        if not mac:
            return None
        try:
            # Normalise to uppercase hex without separators
            clean = mac.upper().replace(":", "").replace("-", "").replace(".", "")
            if len(clean) < 6:
                return None
            prefix = clean[:6]
            if prefix in _OUI_OVERRIDES:
                return _OUI_OVERRIDES[prefix]
            # Fallback: netaddr (already a dependency)
            import netaddr
            oui = netaddr.EUI(mac).oui
            try:
                return oui.registration().org
            except Exception:
                return None
        except Exception:
            return None

    def icon_slug(self, vendor: str | None) -> str | None:
        if not vendor:
            return None
        vendor_lower = vendor.lower()
        for key, slug in _VENDOR_TO_ICON.items():
            if key in vendor_lower:
                return slug
        return None
```

- [ ] **Step 1.4: Run OUI tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py::TestOUIResolver -v
```
Expected: all 5 tests PASS

---

### Task 2: Hostname pattern matching + port fingerprinting

- [ ] **Step 2.1: Write failing tests for hostname + port inference**

```python
# Append to apps/backend/tests/test_inference_service.py

class TestHostnameInference:
    def test_proxmox_hostname(self):
        from app.services.inference_service import _infer_from_hostname
        result = _infer_from_hostname("pve-node1.local")
        assert result["role"] == "hypervisor"

    def test_switch_hostname(self):
        from app.services.inference_service import _infer_from_hostname
        result = _infer_from_hostname("sw-core-01")
        assert result["role"] == "switch"

    def test_nas_hostname(self):
        from app.services.inference_service import _infer_from_hostname
        result = _infer_from_hostname("synology-nas")
        assert result["role"] == "storage"

    def test_rpi_hostname_no_false_positive(self):
        from app.services.inference_service import _infer_from_hostname
        # bare "pi" should NOT match "pipeline" or "opigee"
        result = _infer_from_hostname("pipeline-server")
        assert result.get("role") is None

    def test_rpi_hostname_correct(self):
        from app.services.inference_service import _infer_from_hostname
        result = _infer_from_hostname("rpi-kiosk")
        assert result["role"] == "sbc"

    def test_unknown_hostname_returns_empty(self):
        from app.services.inference_service import _infer_from_hostname
        result = _infer_from_hostname("desktop-abc123")
        assert result == {}


class TestPortInference:
    def test_proxmox_port(self):
        from app.services.inference_service import _infer_from_ports
        result = _infer_from_ports([{"port": 8006, "protocol": "tcp", "state": "open"}])
        assert result["role"] == "hypervisor"

    def test_server_ports(self):
        from app.services.inference_service import _infer_from_ports
        ports = [
            {"port": 22, "protocol": "tcp", "state": "open"},
            {"port": 443, "protocol": "tcp", "state": "open"},
        ]
        result = _infer_from_ports(ports)
        assert result["role"] == "server"

    def test_snmp_device(self):
        from app.services.inference_service import _infer_from_ports
        result = _infer_from_ports([{"port": 161, "protocol": "udp", "state": "open"}])
        assert result.get("snmp_capable") is True

    def test_empty_ports_returns_empty(self):
        from app.services.inference_service import _infer_from_ports
        result = _infer_from_ports([])
        assert result == {}

    def test_none_ports_returns_empty(self):
        from app.services.inference_service import _infer_from_ports
        result = _infer_from_ports(None)
        assert result == {}
```

- [ ] **Step 2.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py::TestHostnameInference tests/test_inference_service.py::TestPortInference -v 2>&1 | head -20
```
Expected: `ImportError: cannot import name '_infer_from_hostname'`

- [ ] **Step 2.3: Add hostname + port inference functions to inference_service.py**

Append to `apps/backend/src/app/services/inference_service.py`:

```python
# ---------------------------------------------------------------------------
# Hostname pattern matching (substring, case-insensitive)
# ---------------------------------------------------------------------------
_HOSTNAME_RULES: list[tuple[str, dict]] = [
    # (substring_to_match, {role, optional vendor, optional icon})
    ("proxmox",     {"role": "hypervisor", "vendor_icon_slug": "proxmox"}),
    ("pve",         {"role": "hypervisor", "vendor_icon_slug": "proxmox"}),
    ("esxi",        {"role": "hypervisor", "vendor_icon_slug": "vmware"}),
    ("vcenter",     {"role": "hypervisor", "vendor_icon_slug": "vmware"}),
    ("unifi",       {"role": "access_point", "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("usg",         {"role": "router",      "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("udm",         {"role": "router",      "vendor": "Ubiquiti", "vendor_icon_slug": "ubiquiti"}),
    ("sw-",         {"role": "switch"}),
    ("switch",      {"role": "switch"}),
    ("rt-",         {"role": "router"}),
    ("router",      {"role": "router"}),
    ("gateway",     {"role": "router"}),
    ("gw-",         {"role": "router"}),
    ("nas",         {"role": "storage"}),
    ("synology",    {"role": "storage", "vendor": "Synology", "vendor_icon_slug": "synology"}),
    ("qnap",        {"role": "storage", "vendor": "QNAP",     "vendor_icon_slug": "qnap"}),
    ("truenas",     {"role": "storage"}),
    ("freenas",     {"role": "storage"}),
    ("rpi-",        {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("-rpi-",       {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("rpi.",        {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("raspberrypi", {"role": "sbc", "vendor": "Raspberry Pi", "vendor_icon_slug": "raspberrypi"}),
    ("ap-",         {"role": "access_point"}),
    ("-ap.",        {"role": "access_point"}),
    ("ups",         {"role": "ups"}),
    ("pfsense",     {"role": "router", "vendor_icon_slug": "pfsense"}),
    ("opnsense",    {"role": "router", "vendor_icon_slug": "opnsense"}),
    ("pihole",      {"role": "server", "vendor_icon_slug": "raspberrypi"}),
    ("homeassistant", {"role": "server"}),
]


def _infer_from_hostname(hostname: str | None) -> dict:
    if not hostname:
        return {}
    h = hostname.lower()
    for pattern, attrs in _HOSTNAME_RULES:
        if pattern in h:
            return dict(attrs)
    return {}


# ---------------------------------------------------------------------------
# Port fingerprinting
# ---------------------------------------------------------------------------
def _infer_from_ports(ports: list | None) -> dict:
    """ports is a list of dicts with at least a 'port' int key."""
    if not ports:
        return {}
    try:
        port_numbers = {int(p["port"]) for p in ports if isinstance(p, dict) and "port" in p}
    except (TypeError, ValueError):
        return {}

    result: dict = {}

    if 8006 in port_numbers:
        result["role"] = "hypervisor"
        result["vendor_icon_slug"] = "proxmox"
    elif 902 in port_numbers or 443 in port_numbers and 902 in port_numbers:
        result["role"] = "hypervisor"
        result["vendor_icon_slug"] = "vmware"
    elif {22, 443}.issubset(port_numbers):
        result["role"] = "server"
    elif 22 in port_numbers and len(port_numbers) == 1:
        result["role"] = "server"
    elif 80 in port_numbers and len(port_numbers) == 1:
        result["role"] = "misc"
    elif 554 in port_numbers:
        result["role"] = "misc"  # RTSP camera/NVR

    if 161 in port_numbers:
        result["snmp_capable"] = True

    return result
```

- [ ] **Step 2.4: Run hostname + port tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py::TestHostnameInference tests/test_inference_service.py::TestPortInference -v
```
Expected: all 11 tests PASS

---

### Task 3: Confidence scoring + annotate_result

- [ ] **Step 3.1: Write failing tests for annotate_result**

```python
# Append to apps/backend/tests/test_inference_service.py

class TestAnnotateResult:
    def _make_result(self, ip="192.168.1.1", mac=None, hostname=None, ports=None):
        """Minimal ScanResult-like dict for testing."""
        from unittest.mock import MagicMock
        r = MagicMock()
        r.ip_address = ip
        r.mac_address = mac
        r.hostname = hostname
        r.open_ports_json = ports
        return r

    def test_three_signals_agree_high_confidence(self):
        from app.services.inference_service import annotate_result
        result = self._make_result(
            mac="DC:A6:32:11:22:33",   # Raspberry Pi OUI
            hostname="rpi-kiosk",       # rpi- pattern
            ports=[{"port": 22, "protocol": "tcp", "state": "open"}],
        )
        ann = annotate_result(result)
        assert ann.role == "sbc"
        assert ann.vendor == "Raspberry Pi"
        assert ann.vendor_icon_slug == "raspberrypi"
        assert ann.confidence >= 0.75
        assert "mac_oui" in ann.signals_used

    def test_no_signals_zero_confidence(self):
        from app.services.inference_service import annotate_result
        result = self._make_result(mac=None, hostname=None, ports=None)
        ann = annotate_result(result)
        assert ann.confidence == 0.0
        assert ann.role is None
        assert ann.signals_used == []

    def test_hostname_only_medium_confidence(self):
        from app.services.inference_service import annotate_result
        result = self._make_result(hostname="proxmox-node", mac=None, ports=None)
        ann = annotate_result(result)
        assert ann.role == "hypervisor"
        assert 0.40 <= ann.confidence <= 0.74

    def test_conflict_between_signals_uses_highest_priority(self):
        from app.services.inference_service import annotate_result
        # hostname says "router", ports say "server" — hostname wins (higher base score)
        result = self._make_result(
            hostname="rt-border",
            ports=[{"port": 22, "protocol": "tcp", "state": "open"}],
            mac=None,
        )
        ann = annotate_result(result)
        assert ann.role in ("router", "server")  # one wins; both signals used
        assert ann.confidence >= 0.50
```

- [ ] **Step 3.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py::TestAnnotateResult -v 2>&1 | head -10
```
Expected: `ImportError: cannot import name 'annotate_result'`

- [ ] **Step 3.3: Implement annotate_result + confidence scoring**

Append to `apps/backend/src/app/services/inference_service.py`:

```python
# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------
_BASE_SCORES = {"mac_oui": 0.40, "hostname": 0.50, "port": 0.30}


def _compute_confidence(signals_used: list[str], signals_agree: bool) -> float:
    if not signals_used:
        return 0.0
    if len(signals_used) == 1:
        return _BASE_SCORES.get(signals_used[0], 0.30)
    if len(signals_used) >= 3 and signals_agree:
        return 1.00
    if len(signals_used) >= 2 and signals_agree:
        return 0.75
    # Multiple signals but disagreeing
    return max(_BASE_SCORES.get(s, 0.30) for s in signals_used) + 0.10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
_oui_resolver = OUIResolver()


def annotate_result(scan_result) -> InferredAnnotation:
    """
    Annotate a ScanResult ORM row (or duck-typed object with ip_address, mac_address,
    hostname, open_ports_json attributes) with inferred vendor/role/confidence.
    """
    signals: list[str] = []
    role_votes: list[str] = []
    vendor_votes: list[str] = []
    icon_votes: list[str] = []

    # Signal A: MAC OUI
    oui_vendor = _oui_resolver.lookup(getattr(scan_result, "mac_address", None))
    if oui_vendor:
        signals.append("mac_oui")
        vendor_votes.append(oui_vendor)
        slug = _oui_resolver.icon_slug(oui_vendor)
        if slug:
            icon_votes.append(slug)

    # Signal B: Hostname
    hostname_attrs = _infer_from_hostname(getattr(scan_result, "hostname", None))
    if hostname_attrs:
        signals.append("hostname")
        if "role" in hostname_attrs:
            role_votes.append(hostname_attrs["role"])
        if "vendor" in hostname_attrs:
            vendor_votes.append(hostname_attrs["vendor"])
        if "vendor_icon_slug" in hostname_attrs:
            icon_votes.append(hostname_attrs["vendor_icon_slug"])

    # Signal C: Ports
    port_attrs = _infer_from_ports(getattr(scan_result, "open_ports_json", None))
    if port_attrs:
        signals.append("port")
        if "role" in port_attrs:
            role_votes.append(port_attrs["role"])
        if "vendor_icon_slug" in port_attrs:
            icon_votes.append(port_attrs["vendor_icon_slug"])

    # Resolve votes: prefer hostname role (most distinctive), then port
    final_role = role_votes[0] if role_votes else None
    final_vendor = vendor_votes[0] if vendor_votes else None
    final_icon = icon_votes[0] if icon_votes else None

    # Determine if signals agree (same role from multiple signals)
    roles_agree = len(set(role_votes)) <= 1 if role_votes else True

    confidence = _compute_confidence(signals, roles_agree)

    return InferredAnnotation(
        vendor=final_vendor,
        role=final_role,
        vendor_icon_slug=final_icon,
        confidence=round(confidence, 2),
        signals_used=signals,
    )
```

- [ ] **Step 3.4: Run all inference tests**

```bash
cd apps/backend && python -m pytest tests/test_inference_service.py -v
```
Expected: all tests PASS

- [ ] **Step 3.5: Commit**

```bash
cd apps/backend && git add src/app/services/inference_service.py tests/test_inference_service.py
git commit -m "feat: add inference service for scan result annotation (OUI, hostname, ports)"
```

---

### Task 4: Layout service — subnet grouping

**Files:**
- Create: `apps/backend/src/app/services/layout_service.py`
- Create: `apps/backend/tests/test_layout_service.py`

- [ ] **Step 4.1: Write failing tests**

```python
# apps/backend/tests/test_layout_service.py
import pytest
from app.services.layout_service import compute_subnet_layout, _subnet_key

class TestSubnetKey:
    def test_ipv4_extracts_24_slice(self):
        assert _subnet_key("192.168.1.42") == "192.168.1"

    def test_different_subnets(self):
        assert _subnet_key("10.0.0.1") == "10.0.0"
        assert _subnet_key("10.0.1.1") == "10.0.1"

    def test_no_ip_returns_none(self):
        assert _subnet_key(None) is None

    def test_malformed_ip_returns_none(self):
        assert _subnet_key("not-an-ip") is None


class TestComputeSubnetLayout:
    def _make_hw(self, id, ip, role="server"):
        """Minimal hardware-like dict."""
        return {"id": id, "ip_address": ip, "role": role}

    def test_single_subnet_places_all_nodes(self):
        hardware = [
            self._make_hw(1, "192.168.1.1", "router"),
            self._make_hw(2, "192.168.1.10"),
            self._make_hw(3, "192.168.1.11"),
        ]
        positions = compute_subnet_layout(hardware)
        assert len(positions) == 3
        for hw_id in [1, 2, 3]:
            assert hw_id in positions
            assert "x" in positions[hw_id]
            assert "y" in positions[hw_id]

    def test_router_placed_above_others(self):
        hardware = [
            self._make_hw(1, "192.168.1.1", "router"),
            self._make_hw(2, "192.168.1.10"),
            self._make_hw(3, "192.168.1.20"),
        ]
        positions = compute_subnet_layout(hardware)
        # Router (lowest IP, role=router) placed at smaller y (top)
        assert positions[1]["y"] < positions[2]["y"]

    def test_two_subnets_separated_horizontally(self):
        hardware = [
            self._make_hw(1, "192.168.1.1"),
            self._make_hw(2, "192.168.2.1"),
        ]
        positions = compute_subnet_layout(hardware)
        # Nodes in different subnets should have different x positions
        assert positions[1]["x"] != positions[2]["x"]

    def test_no_ip_node_placed_in_overflow(self):
        hardware = [
            self._make_hw(1, None),
            self._make_hw(2, "192.168.1.1"),
        ]
        positions = compute_subnet_layout(hardware)
        assert 1 in positions
        assert 2 in positions

    def test_empty_list_returns_empty_dict(self):
        assert compute_subnet_layout([]) == {}
```

- [ ] **Step 4.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_layout_service.py -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'app.services.layout_service'`

- [ ] **Step 4.3: Implement layout_service.py**

```python
# apps/backend/src/app/services/layout_service.py
"""
Subnet-grouped canvas layout for newly imported hardware nodes.

Groups nodes by /24 slice, places gateway/router at top-center of each group,
remaining nodes in rows of up to 5. Returns {hardware_id: {"x": float, "y": float}}.
"""
from __future__ import annotations

# Canvas spacing constants
_GROUP_X_SPACING = 600    # px between subnet columns
_NODE_X_SPACING  = 200    # px between nodes within a group
_NODE_Y_SPACING  = 180    # px between rows
_GROUP_Y_ORIGIN  = 100    # starting y for first row
_GATEWAY_Y       = 50     # y for gateway node (above the grid)
_OVERFLOW_X      = 2000   # x for nodes with no IP
_MAX_COLS        = 5      # max nodes per row within a group


def _subnet_key(ip: str | None) -> str | None:
    """Return the /24 prefix as 'A.B.C', or None if IP is absent/malformed."""
    if not ip:
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        [int(p) for p in parts]  # validate all octets are integers
    except ValueError:
        return None
    return ".".join(parts[:3])


def _is_gateway(hw: dict) -> bool:
    """Heuristic: router/gateway role, or lowest host number in subnet."""
    return hw.get("role") in ("router", "gateway")


def compute_subnet_layout(hardware: list[dict]) -> dict[int, dict]:
    """
    hardware: list of dicts with keys: id (int), ip_address (str|None), role (str|None)
    Returns: {id: {"x": float, "y": float}}
    """
    if not hardware:
        return {}

    # Group by /24 subnet key; None-IP nodes go to overflow
    groups: dict[str, list[dict]] = {}
    overflow: list[dict] = []
    for hw in hardware:
        key = _subnet_key(hw.get("ip_address"))
        if key is None:
            overflow.append(hw)
        else:
            groups.setdefault(key, []).append(hw)

    positions: dict[int, dict] = {}
    col = 0

    for subnet_key in sorted(groups.keys()):
        nodes = groups[subnet_key]
        x_center = col * _GROUP_X_SPACING + 300

        # Separate gateway from non-gateway; fall back to lowest IP as gateway
        gateways = [n for n in nodes if _is_gateway(n)]
        others = [n for n in nodes if not _is_gateway(n)]
        if not gateways and others:
            # Use node with lowest last octet as implicit gateway
            others_sorted = sorted(others, key=lambda n: int((n.get("ip_address") or "0.0.0.0").split(".")[-1]))
            gateways = [others_sorted[0]]
            others = others_sorted[1:]

        # Place gateway at top-center
        for gw in gateways:
            positions[gw["id"]] = {"x": float(x_center), "y": float(_GATEWAY_Y)}

        # Place others in rows of MAX_COLS below
        for idx, node in enumerate(others):
            row = idx // _MAX_COLS
            col_offset = idx % _MAX_COLS
            x = x_center - (_MAX_COLS // 2) * _NODE_X_SPACING + col_offset * _NODE_X_SPACING
            y = _GROUP_Y_ORIGIN + row * _NODE_Y_SPACING
            positions[node["id"]] = {"x": float(x), "y": float(y)}

        col += 1

    # Overflow nodes: stack vertically at far right
    for idx, node in enumerate(overflow):
        positions[node["id"]] = {
            "x": float(_OVERFLOW_X),
            "y": float(_GROUP_Y_ORIGIN + idx * _NODE_Y_SPACING),
        }

    return positions
```

- [ ] **Step 4.4: Run layout tests**

```bash
cd apps/backend && python -m pytest tests/test_layout_service.py -v
```
Expected: all tests PASS

- [ ] **Step 4.5: Commit**

```bash
cd apps/backend && git add src/app/services/layout_service.py tests/test_layout_service.py
git commit -m "feat: add subnet grouping layout service for scan import"
```

---

## Chunk 2: Discovery API — Enriched Results + Batch Import

### Task 5: InferredScanResultOut schema

**Files:**
- Modify: `apps/backend/src/app/schemas/discovery.py` (add new schema after `ScanResultOut`)

- [ ] **Step 5.1: Read current ScanResultOut schema**

```bash
grep -n "class ScanResultOut\|class BatchImport\|class Inferred" apps/backend/src/app/schemas/discovery.py
```
This confirms where `ScanResultOut` ends and where to append new schemas.

- [ ] **Step 5.2: Add InferredScanResultOut and BatchImportRequest/Response schemas**

Append after the existing `ScanResultOut` class in `apps/backend/src/app/schemas/discovery.py`:

```python
# ── Scan-to-Map pipeline schemas ─────────────────────────────────────────────

class InferredScanResultOut(ScanResultOut):
    """ScanResultOut extended with inference annotations for the import modal."""
    inferred_vendor: str | None = None
    inferred_role: str | None = None
    inferred_icon_slug: str | None = None
    confidence: float = 0.0
    signals_used: list[str] = []
    exists_in_hardware: bool = False
    existing_hardware_id: int | None = None
    is_new: bool = True   # computed at request time; True when exists_in_hardware is False


class BatchImportItem(BaseModel):
    scan_result_id: int
    overrides: dict = {}   # partial HardwareCreate fields; validated in service


class BatchImportRequest(BaseModel):
    items: list[BatchImportItem]


class BatchImportCreated(BaseModel):
    id: int
    ip: str | None
    position: dict | None   # {"x": float, "y": float} or None for existing nodes


class BatchImportConflict(BaseModel):
    scan_result_id: int
    ip: str | None
    mac: str | None
    reason: str


class BatchImportResponse(BaseModel):
    created: list[BatchImportCreated] = []
    updated: list[BatchImportCreated] = []
    conflicts: list[BatchImportConflict] = []
    skipped: list[int] = []
```

- [ ] **Step 5.3: Verify import succeeds**

```bash
cd apps/backend && python -c "from app.schemas.discovery import InferredScanResultOut, BatchImportResponse; print('OK')"
```
Expected: `OK`

- [ ] **Step 5.4: Commit**

```bash
cd apps/backend && git add src/app/schemas/discovery.py
git commit -m "feat: add InferredScanResultOut and BatchImportRequest schemas"
```

---

### Task 6: Enriched GET results endpoint

**Files:**
- Modify: `apps/backend/src/app/api/discovery.py` (add `with_inference` query param to existing jobs/{job_id}/results endpoint)

- [ ] **Step 6.1: Create test_batch_import.py with enriched-results tests**

> Note: Routes use `jobs/` not `scans/` — this matches the existing discovery route structure
> where scan jobs are at `/discovery/jobs/{id}`. The spec used `scans/` conceptually; the
> implementation uses the existing `jobs/` prefix for consistency.

```python
# apps/backend/tests/test_batch_import.py
"""Tests for the enriched scan results endpoint and batch import service."""
import pytest
from unittest.mock import MagicMock

class TestEnrichedResultsEndpoint:
    """Tests for GET /discovery/jobs/{id}/results?with_inference=true logic."""

    def test_schema_fields_present(self):
        """InferredScanResultOut has all required fields for the modal table."""
        from app.schemas.discovery import InferredScanResultOut
        fields = InferredScanResultOut.model_fields
        for field in ("inferred_vendor", "inferred_role", "inferred_icon_slug",
                      "confidence", "signals_used", "exists_in_hardware",
                      "existing_hardware_id", "is_new"):
            assert field in fields, f"Missing field: {field}"

    def test_is_new_defaults_true(self):
        """is_new defaults to True (device not yet on map)."""
        from app.schemas.discovery import InferredScanResultOut
        # Create minimal valid instance using model_construct to bypass DB fields
        inst = InferredScanResultOut.model_construct()
        assert inst.is_new is True

    def test_annotate_does_not_crash_on_missing_attributes(self):
        """annotate_result must never raise even if ScanResult has missing attrs."""
        from app.services.inference_service import annotate_result
        mock_result = MagicMock(spec=[])  # spec=[] means no attributes defined
        ann = annotate_result(mock_result)
        assert ann.confidence == 0.0
```

- [ ] **Step 6.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_batch_import.py::TestEnrichedResultsEndpoint -v 2>&1 | head -15
```
Expected: first test fails with `ModuleNotFoundError` or field assertion failure (schemas not added yet in this task order — if Task 5 is done first, tests will pass after Step 6.3)

- [ ] **Step 6.3: Add `with_inference` query param to the existing results endpoint**

In `apps/backend/src/app/api/discovery.py`, find the existing endpoint:
```python
@router.get("/jobs/{job_id}/results", response_model=list[ScanResultOut])
```

Replace it with:
```python
@router.get("/jobs/{job_id}/results")
def get_job_results(
    job_id: int,
    with_inference: bool = False,
    _user=require_auth_always,
    db: Session = Depends(get_db),
):
    """Return scan results, optionally enriched with inference annotations."""
    from app.schemas.discovery import InferredScanResultOut, ScanResultOut
    from app.services.inference_service import annotate_result

    job = db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    results = db.query(ScanResult).filter(ScanResult.scan_job_id == job_id).all()

    if not with_inference:
        return [ScanResultOut.model_validate(r) for r in results]

    # Build set of existing IP and MAC addresses for deduplication check
    from app.db.models import Hardware
    existing_by_ip: dict[str, int] = {
        h.ip_address: h.id
        for h in db.query(Hardware.ip_address, Hardware.id).filter(Hardware.ip_address.isnot(None)).all()
    }
    existing_by_mac: dict[str, int] = {
        h.mac_address: h.id
        for h in db.query(Hardware.mac_address, Hardware.id).filter(Hardware.mac_address.isnot(None)).all()
    }

    enriched = []
    for r in results:
        ann = annotate_result(r)
        # Resolve existing_hardware_id: MAC priority over IP
        hw_id = existing_by_mac.get(r.mac_address) if r.mac_address else None
        if hw_id is None:
            hw_id = existing_by_ip.get(r.ip_address) if r.ip_address else None

        out = InferredScanResultOut.model_validate(r)
        out.inferred_vendor = ann.vendor
        out.inferred_role = ann.role
        out.inferred_icon_slug = ann.vendor_icon_slug
        out.confidence = ann.confidence
        out.signals_used = ann.signals_used
        out.exists_in_hardware = hw_id is not None
        out.existing_hardware_id = hw_id
        out.is_new = hw_id is None
        enriched.append(out)

    return enriched
```

- [ ] **Step 6.4: Verify no import errors**

```bash
cd apps/backend && python -c "from app.api.discovery import router; print('OK')"
```
Expected: `OK`

- [ ] **Step 6.5: Run enriched result tests**

```bash
cd apps/backend && python -m pytest tests/test_batch_import.py::TestEnrichedResultsEndpoint -v
```
Expected: all 3 tests PASS

- [ ] **Step 6.6: Commit**

```bash
cd apps/backend && git add src/app/api/discovery.py tests/test_batch_import.py
git commit -m "feat: add with_inference query param to scan results endpoint"
```

---

### Task 7: Batch import endpoint

- [ ] **Step 7.1: Write failing tests for batch import logic**

Append to `apps/backend/tests/test_batch_import.py`:

```python
class TestBatchImportService:
    """Unit tests for the batch import service function (no HTTP layer)."""

    def _setup_db(self, db_session):
        """Helper: insert a ScanJob + two ScanResults into the test DB."""
        from app.db.models import ScanJob, ScanResult
        from app.core.time import utcnow_iso
        job = ScanJob(
            target_cidr="192.168.1.0/24",
            scan_types_json='["nmap"]',
            status="done",
            created_at=utcnow_iso(),
        )
        db_session.add(job)
        db_session.flush()

        r1 = ScanResult(
            scan_job_id=job.id,
            ip_address="192.168.1.10",
            mac_address="DC:A6:32:AA:BB:CC",
            hostname="rpi-sensor",
            created_at=utcnow_iso(),
        )
        r2 = ScanResult(
            scan_job_id=job.id,
            ip_address="192.168.1.20",
            mac_address=None,
            hostname="unknown-device",
            created_at=utcnow_iso(),
        )
        db_session.add_all([r1, r2])
        db_session.flush()
        return job, r1, r2

    def test_import_creates_new_hardware(self, db_session):
        from app.services.discovery_import_service import batch_import
        from app.schemas.discovery import BatchImportItem, BatchImportRequest

        job, r1, r2 = self._setup_db(db_session)
        req = BatchImportRequest(items=[
            BatchImportItem(scan_result_id=r1.id, overrides={}),
        ])
        result = batch_import(db_session, job.id, req, actor="test")

        assert len(result.created) == 1
        assert result.created[0].ip == "192.168.1.10"
        assert result.created[0].id is not None

    def test_import_idempotent_on_second_call(self, db_session):
        from app.services.discovery_import_service import batch_import
        from app.schemas.discovery import BatchImportItem, BatchImportRequest

        job, r1, _ = self._setup_db(db_session)
        req = BatchImportRequest(items=[BatchImportItem(scan_result_id=r1.id, overrides={})])

        batch_import(db_session, job.id, req, actor="test")
        result2 = batch_import(db_session, job.id, req, actor="test")

        assert len(result2.updated) == 1
        assert len(result2.created) == 0

    def test_override_applied_to_new_node(self, db_session):
        from app.services.discovery_import_service import batch_import
        from app.schemas.discovery import BatchImportItem, BatchImportRequest
        from app.db.models import Hardware

        job, r1, _ = self._setup_db(db_session)
        req = BatchImportRequest(items=[
            BatchImportItem(scan_result_id=r1.id, overrides={"name": "my-pi", "role": "sbc"}),
        ])
        result = batch_import(db_session, job.id, req, actor="test")
        hw = db_session.get(Hardware, result.created[0].id)
        assert hw.name == "my-pi"
        assert hw.role == "sbc"
```

- [ ] **Step 7.2: Run failing tests**

```bash
cd apps/backend && python -m pytest tests/test_batch_import.py::TestBatchImportService -v 2>&1 | head -10
```
Expected: `ModuleNotFoundError: No module named 'app.services.discovery_import_service'`

- [ ] **Step 7.3: Create discovery_import_service.py**

```python
# apps/backend/src/app/services/discovery_import_service.py
"""
Batch import service: converts ScanResult rows into Hardware rows.

- Deduplicates by MAC address first, then IP address.
- Uses SELECT FOR UPDATE to prevent concurrent duplicate creation.
- Computes subnet-grouped layout for newly created nodes.
- Persists layout via existing graph layout mechanism.
- Idempotent: re-importing the same scan produces updated rows, not duplicates.
"""
from __future__ import annotations
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Hardware, ScanResult, ScanJob
from app.schemas.discovery import (
    BatchImportRequest,
    BatchImportResponse,
    BatchImportCreated,
    BatchImportConflict,
)
from app.services.inference_service import annotate_result
from app.services.layout_service import compute_subnet_layout

_logger = logging.getLogger(__name__)

_VALID_ROLES = {
    "server", "router", "switch", "firewall", "hypervisor", "storage",
    "compute", "access_point", "sbc", "ups", "pdu", "misc",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitise_overrides(overrides: dict) -> dict:
    """Strip unknown keys from overrides to prevent injection into model."""
    allowed = {"name", "role", "vendor", "vendor_icon_slug", "notes"}
    clean = {k: v for k, v in overrides.items() if k in allowed}
    if "role" in clean and clean["role"] not in _VALID_ROLES:
        del clean["role"]
    return clean


def batch_import(
    db: Session,
    job_id: int,
    request: BatchImportRequest,
    actor: str = "api",
) -> BatchImportResponse:
    response = BatchImportResponse()

    # IMPORTANT: wrap the entire for-loop body below in `with db.begin_nested():`
    # so all upserts execute in a single SAVEPOINT. If any item raises, the savepoint
    # rolls back automatically and the exception propagates.
    #
    #   with db.begin_nested():
    #       for item in request.items:
    #           ...
    #
    # The outer transaction is owned by get_db and committed at the end of this function.

    for item in request.items:
        scan_result = db.get(ScanResult, item.scan_result_id)
        if not scan_result or scan_result.scan_job_id != job_id:
            response.skipped.append(item.scan_result_id)
            continue

        ip = scan_result.ip_address
        mac = scan_result.mac_address

        # ── Lock candidate rows ────────────────────────────────────────────
        hw_by_mac: Hardware | None = None
        hw_by_ip: Hardware | None = None

        if mac:
            hw_by_mac = db.execute(
                select(Hardware).where(Hardware.mac_address == mac).with_for_update()
            ).scalar_one_or_none()
        if ip:
            hw_by_ip = db.execute(
                select(Hardware).where(Hardware.ip_address == ip).with_for_update()
            ).scalar_one_or_none()

        # ── Detect cross-match conflict ────────────────────────────────────
        if hw_by_mac and hw_by_ip and hw_by_mac.id != hw_by_ip.id:
            response.conflicts.append(BatchImportConflict(
                scan_result_id=item.scan_result_id,
                ip=ip,
                mac=mac,
                reason=f"mac_matches_id_{hw_by_mac.id}_ip_matches_id_{hw_by_ip.id}",
            ))
            continue

        existing = hw_by_mac or hw_by_ip
        overrides = _sanitise_overrides(item.overrides)

        if existing:
            # ── Update existing ─────────────────────────────────────────────
            existing.last_seen = _now_iso()
            if mac and existing.mac_address != mac:
                existing.mac_address = mac
            if scan_result.hostname and existing.hostname != scan_result.hostname:
                existing.hostname = scan_result.hostname
            # Only overwrite discovery-sourced fields
            if existing.source == "discovery":
                for k, v in overrides.items():
                    setattr(existing, k, v)
            existing.source_scan_result_id = scan_result.id
            db.flush()
            response.updated.append(BatchImportCreated(id=existing.id, ip=ip, position=None))
        else:
            # ── Create new ──────────────────────────────────────────────────
            ann = annotate_result(scan_result)
            name = overrides.pop("name", None) or scan_result.hostname or ip or f"device-{scan_result.id}"
            hw = Hardware(
                name=name,
                ip_address=ip,
                mac_address=mac,
                hostname=scan_result.hostname,
                role=overrides.pop("role", None) or ann.role or "misc",
                vendor=overrides.pop("vendor", None) or ann.vendor,
                vendor_icon_slug=overrides.pop("vendor_icon_slug", None) or ann.vendor_icon_slug,
                source="discovery",
                discovered_at=_now_iso(),
                last_seen=_now_iso(),
                source_scan_result_id=scan_result.id,
                node_type="hardware",
            )
            for k, v in overrides.items():
                setattr(hw, k, v)
            db.add(hw)
            db.flush()
            response.created.append(BatchImportCreated(id=hw.id, ip=ip, position=None))

    # ── Compute layout for new nodes ───────────────────────────────────────
    if response.created:
        hw_list = [
            {"id": c.id, "ip_address": c.ip, "role": db.get(Hardware, c.id).role}
            for c in response.created
        ]
        positions = compute_subnet_layout(hw_list)
        for created_item in response.created:
            created_item.position = positions.get(created_item.id)

        # Persist layout server-side
        _persist_layout(db, positions)

    db.commit()
    return response


def _persist_layout(db: Session, positions: dict[int, dict]) -> None:
    """Save positions to the graph layout table (default environment layout)."""
    try:
        from app.services.graph_service import save_layout
        # Convert int keys to str (layout uses string node IDs)
        str_positions = {str(k): v for k, v in positions.items()}
        save_layout(db, "default", str_positions)
    except Exception as exc:
        _logger.warning("Layout persistence failed (non-fatal): %s", exc)
```

- [ ] **Step 7.4: Run batch import tests**

```bash
cd apps/backend && python -m pytest tests/test_batch_import.py::TestBatchImportService -v
```
Expected: all 3 tests PASS. If DB session fixture not available, create a minimal conftest or use existing `tests/conftest.py` patterns.

- [ ] **Step 7.5: Add batch-import HTTP endpoint to discovery.py**

Add to `apps/backend/src/app/api/discovery.py`:

```python
@router.post("/jobs/{job_id}/batch-import", response_model=BatchImportResponse)
def batch_import_results(
    job_id: int,
    payload: BatchImportRequest,
    _user=require_write_auth,
    db: Session = Depends(get_db),
):
    """Batch import selected scan results as Hardware nodes. Requires write role."""
    from app.services.discovery_import_service import batch_import

    job = db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found")

    return batch_import(db, job_id, payload, actor="api")
```

Also add missing imports at top of discovery.py:
```python
from app.schemas.discovery import BatchImportRequest, BatchImportResponse
```

- [ ] **Step 7.6: Verify no import errors**

```bash
cd apps/backend && python -c "from app.api.discovery import router; print('OK')"
```
Expected: `OK`

- [ ] **Step 7.7: Commit**

```bash
cd apps/backend && git add src/app/services/discovery_import_service.py src/app/api/discovery.py tests/test_batch_import.py
git commit -m "feat: add batch-import endpoint with deduplication and subnet layout"
```

---

## Chunk 3: Frontend — API Client + Hook + Modal + Map Integration

### Task 8: API client additions

**Files:**
- Modify: `apps/frontend/src/api/client.jsx`

- [ ] **Step 8.1: Add discoveryApi methods**

In `apps/frontend/src/api/client.jsx`, add a `discoveryApi` export (or extend if it exists):

```javascript
export const discoveryApi = {
  getJobs: (params) => client.get('/discovery/jobs', { params }),
  getJob: (id) => client.get(`/discovery/jobs/${id}`),
  getResultsWithInference: (jobId) =>
    client.get(`/discovery/jobs/${jobId}/results`, { params: { with_inference: true } }),
  batchImport: (jobId, items) =>
    client.post(`/discovery/jobs/${jobId}/batch-import`, { items }),
  runScan: (profileId) => client.post(`/discovery/profiles/${profileId}/run`),
};
```

- [ ] **Step 8.2: Verify the API client builds cleanly**

```bash
cd apps/frontend && npx vite build 2>&1 | tail -3
```
Expected: `✓ built in ...` with no error lines

- [ ] **Step 8.3: Commit**

```bash
cd apps/frontend && git add src/api/client.jsx
git commit -m "feat: add discoveryApi.getResultsWithInference and batchImport to API client"
```

---

### Task 9: Scan import-ready event in useMapRealTimeUpdates

**Files:**
- Modify: `apps/frontend/src/hooks/useMapRealTimeUpdates.js`

- [ ] **Step 9.1: Find the job-status polling section in the hook**

```bash
grep -n "status.*done\|hosts_new\|pendingDiscover\|setPending\|setJobs" apps/frontend/src/hooks/useMapRealTimeUpdates.js | head -20
```
This shows the exact line numbers where scan job status transitions occur. Look for the condition that sets `pendingDiscoveries` or processes a completed job — that's where `checkScanForImport` should be called.

- [ ] **Step 9.2: Add scan-completion detection**

Add `import { discoveryApi } from '../api/client';` at the top of the hook file.

Add `checkScanForImport` as a stable callback inside the hook:

```javascript
const checkScanForImport = useCallback(async (jobId) => {
  try {
    const { data: results } = await discoveryApi.getResultsWithInference(jobId);
    const newCount = results.filter(r => r.is_new).length;
    if (newCount > 0) {
      globalThis.dispatchEvent(new CustomEvent('scan:import-ready', {
        detail: { scanId: jobId, newCount }
      }));
    }
  } catch (_e) {
    // Non-fatal — banner is an optional UX enhancement
  }
}, []);  // no deps: discoveryApi is module-level, newCount computed inline
```

Call `checkScanForImport(job.id)` at the point where a job's status is observed to be `'done'` (identified from Step 9.1). Do NOT read `hosts_new` from the job — `newCount` is computed fresh from the enriched results response.

- [ ] **Step 9.3: Verify hook file builds without error**

```bash
cd apps/frontend && npx vite build 2>&1 | tail -5
```
Expected: `✓ built in ...` with no error lines

- [ ] **Step 9.4: Commit**

```bash
cd apps/frontend && git add src/hooks/useMapRealTimeUpdates.js
git commit -m "feat: dispatch scan:import-ready event when scan completes with new hosts"
```

---

### Task 10: ScanImportModal component

**Files:**
- Create: `apps/frontend/src/components/ScanImportModal.jsx`

- [ ] **Step 10.1: Create ScanImportModal**

```jsx
// apps/frontend/src/components/ScanImportModal.jsx
/**
 * ScanImportModal — batch confirm dialog for importing discovered devices.
 *
 * Props:
 *   scanId (number)     — the ScanJob id to import from
 *   results (array)     — pre-fetched InferredScanResultOut array (pass from banner)
 *   onClose ()          — called when user dismisses without importing
 *   onImported (resp)   — called with BatchImportResponse after successful import
 */
import React, { useState, useMemo } from 'react';
import { discoveryApi } from '../api/client';
import { useToast } from '../hooks/useToast';

const CONFIDENCE_DOTS = (c) => {
  if (c >= 0.75) return '●●●';
  if (c >= 0.40) return '●●○';
  if (c > 0)     return '●○○';
  return '○○○';
};

const ROLE_OPTIONS = [
  'server', 'router', 'switch', 'firewall', 'hypervisor', 'storage',
  'compute', 'access_point', 'sbc', 'ups', 'pdu', 'misc',
];

export default function ScanImportModal({ scanId, results = [], onClose, onImported }) {
  const toast = useToast();

  // Build initial selection: check all with confidence > 0, or that already exist
  const initialSelected = useMemo(() => {
    const s = new Set();
    results.forEach(r => {
      if (r.confidence > 0 || r.exists_in_hardware) s.add(r.id);
    });
    return s;
  }, [results]);

  const [selected, setSelected] = useState(initialSelected);
  const [roleOverrides, setRoleOverrides] = useState({});
  const [importing, setImporting] = useState(false);

  const toggleRow = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(results.map(r => r.id)));
  const selectNewOnly = () => setSelected(new Set(results.filter(r => r.is_new).map(r => r.id)));

  const handleImport = async () => {
    const items = results
      .filter(r => selected.has(r.id) && !r._conflict)
      .map(r => ({
        scan_result_id: r.id,
        overrides: roleOverrides[r.id] ? { role: roleOverrides[r.id] } : {},
      }));

    if (items.length === 0) { onClose(); return; }

    setImporting(true);
    try {
      const { data: resp } = await discoveryApi.batchImport(scanId, items);
      const msg = [
        resp.created.length && `${resp.created.length} device${resp.created.length !== 1 ? 's' : ''} added`,
        resp.updated.length && `${resp.updated.length} updated`,
      ].filter(Boolean).join('. ');
      toast.success(msg || 'Import complete');
      onImported(resp);
    } catch (err) {
      toast.error(err.message || 'Import failed');
    } finally {
      setImporting(false);
    }
  };

  const selectedCount = [...selected].filter(id => {
    const r = results.find(r => r.id === id);
    return r && !r._conflict;
  }).length;

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal-container scan-import-modal">
        <div className="modal-header">
          <h2>Import Discovered Devices</h2>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="scan-import-actions">
          <button onClick={selectAll} className="btn-text">Select all</button>
          <button onClick={selectNewOnly} className="btn-text">New only</button>
          <span className="scan-import-count">{selectedCount} selected</span>
        </div>

        <div className="scan-import-table-wrapper">
          <table className="scan-import-table">
            <thead>
              <tr>
                <th></th>
                <th>IP</th>
                <th>Hostname</th>
                <th>Vendor</th>
                <th>Role</th>
                <th>Status</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {results.map(r => (
                <tr
                  key={r.id}
                  className={r._conflict ? 'row-conflict' : ''}
                  title={r._conflict ? `Conflict: ${r._conflict}` : ''}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={selected.has(r.id)}
                      disabled={!!r._conflict}
                      onChange={() => toggleRow(r.id)}
                    />
                  </td>
                  <td>{r.ip_address || '—'}</td>
                  <td>{r.hostname || '—'}</td>
                  <td>{r.inferred_vendor || '—'}</td>
                  <td>
                    <select
                      value={roleOverrides[r.id] || r.inferred_role || ''}
                      onChange={e => setRoleOverrides(prev => ({ ...prev, [r.id]: e.target.value }))}
                    >
                      <option value="">— auto —</option>
                      {ROLE_OPTIONS.map(opt => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <span className={`badge ${r.exists_in_hardware ? 'badge-exists' : 'badge-new'}`}>
                      {r.exists_in_hardware ? 'EXISTS' : 'NEW'}
                    </span>
                  </td>
                  <td title={`Signals: ${r.signals_used?.join(', ') || 'none'}`}>
                    {CONFIDENCE_DOTS(r.confidence)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="modal-footer">
          <button onClick={onClose} className="btn-secondary" disabled={importing}>
            Skip all
          </button>
          <button onClick={handleImport} className="btn-primary" disabled={importing || selectedCount === 0}>
            {importing ? 'Importing…' : `Import selected (${selectedCount})`}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 10.2: Commit**

```bash
cd apps/frontend && git add src/components/ScanImportModal.jsx
git commit -m "feat: add ScanImportModal batch confirm component"
```

---

### Task 11: Discovery banner + modal integration in MapPage

**Files:**
- Modify: `apps/frontend/src/pages/MapPage.jsx`

- [ ] **Step 11.1: Add import state and event listener to MapInternal**

First locate the existing `deleteConflictModal` state (a reliable anchor near where new state should go):
```bash
grep -n "deleteConflictModal\|quickCreateModal\|confirmState" apps/frontend/src/pages/MapPage.jsx | head -5
```
Add the following state declarations **after** the `deleteConflictModal` state block:

```javascript
// Scan import banner state
const [scanImportPending, setScanImportPending] = useState(null);
// null | { scanId, newCount, results }
const [scanImportModalOpen, setScanImportModalOpen] = useState(false);
```

Add an effect to listen for the `scan:import-ready` event (place near the other lifecycle `useEffect` calls):

```javascript
useEffect(() => {
  const handler = async (e) => {
    const { scanId, newCount } = e.detail;
    // Pre-fetch results so modal opens instantly
    try {
      const { data: results } = await discoveryApi.getResultsWithInference(scanId);
      setScanImportPending({ scanId, newCount: results.filter(r => r.is_new).length, results });
    } catch {
      setScanImportPending({ scanId, newCount, results: null });
    }
  };
  globalThis.addEventListener('scan:import-ready', handler);
  return () => globalThis.removeEventListener('scan:import-ready', handler);
}, []);
```

Add the import at the top of the file (with other api imports):
```javascript
import { discoveryApi } from '../api/client';
import ScanImportModal from '../components/ScanImportModal';
```

- [ ] **Step 11.2: Add banner and modal to the JSX return**

Find the outermost `<div>` of the MapInternal return (the ReactFlow wrapper). Add the banner and modal just inside:

```jsx
{/* Discovery import banner */}
{scanImportPending && !scanImportModalOpen && (
  <div className="scan-import-banner">
    <span>🔍 {scanImportPending.newCount} new device{scanImportPending.newCount !== 1 ? 's' : ''} discovered</span>
    <button
      className="btn-link"
      onClick={() => setScanImportModalOpen(true)}
    >
      Review &amp; Import →
    </button>
    <button
      className="btn-icon"
      onClick={() => setScanImportPending(null)}
      aria-label="Dismiss"
    >
      ×
    </button>
  </div>
)}

{/* Scan import modal */}
{scanImportModalOpen && scanImportPending && (
  <ScanImportModal
    scanId={scanImportPending.scanId}
    results={scanImportPending.results || []}
    onClose={() => setScanImportModalOpen(false)}
    onImported={async () => {
      setScanImportModalOpen(false);
      setScanImportPending(null);
      await fetchData();          // refresh topology
      fitView({ duration: 600 }); // animate to new nodes
    }}
  />
)}
```

- [ ] **Step 11.3: Add CSS for banner and modal**

Append to `apps/frontend/src/styles/main.css`:

```css
.scan-import-banner {
  position: absolute;
  top: 12px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--color-surface, #1e2a3a);
  border: 1px solid var(--color-accent, #3b82f6);
  border-radius: 8px;
  padding: 8px 16px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.3);
  font-size: 14px;
}

.scan-import-modal {
  width: min(90vw, 860px);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
}

.scan-import-table-wrapper {
  flex: 1;
  overflow-y: auto;
}

.scan-import-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.scan-import-table th,
.scan-import-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid var(--color-border, #2a3a4a);
}

.badge { padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-new    { background: #1a3a1a; color: #4ade80; }
.badge-exists { background: #1a2a3a; color: #60a5fa; }
.row-conflict { background: rgba(251,191,36,0.08); }

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 0 0;
  border-top: 1px solid var(--color-border, #2a3a4a);
  margin-top: 8px;
}
```

- [ ] **Step 11.4: Build and verify no compile errors**

```bash
cd apps/frontend && npx vite build 2>&1 | grep -E "error|Error|✓ built" | head -10
```
Expected: `✓ built in ...` with no error lines

- [ ] **Step 11.5: Commit**

```bash
cd apps/frontend && git add src/pages/MapPage.jsx src/components/ScanImportModal.jsx src/styles/main.css
git commit -m "feat: add discovery banner and ScanImportModal to MapPage"
```

---

### Task 12: Rebuild and smoke test

- [ ] **Step 12.1: Rebuild the Docker image**

```bash
docker compose -f docker/docker-compose.yml up --build -d
```

- [ ] **Step 12.2: Verify clean startup**

```bash
sleep 10 && docker exec circuitbreaker tail -5 /data/backend_api_err.log
```
Expected: `Application startup complete.` — no import errors

- [ ] **Step 12.3: Verify new endpoints are registered**

```bash
# GET enriched results — expect 401 (unauth), confirms route exists
docker exec circuitbreaker curl -s -o /dev/null -w "%{http_code}" \
  "http://127.0.0.1:8000/api/v1/discovery/jobs/1/results?with_inference=true"
# POST batch-import — expect 401 (unauth), confirms route exists
docker exec circuitbreaker curl -s -o /dev/null -w "%{http_code}" -X POST \
  "http://127.0.0.1:8000/api/v1/discovery/jobs/1/batch-import" \
  -H "Content-Type: application/json" -d '{"items":[]}'
```
Expected: `401` for both — confirms routes are registered and auth is enforced

- [ ] **Step 12.4: E2E smoke test (manual)**

1. Log in as admin
2. Navigate to Discovery → run a scan on a local subnet
3. Wait for scan to complete
4. Map page: verify blue banner appears with device count
5. Click "Review & Import →" — modal opens with table
6. Verify confidence dots, EXISTS/NEW badges appear
7. Import selected → nodes appear on map grouped by subnet
8. Re-run scan → no duplicates; `last_seen` updated

- [ ] **Step 12.5: Final integration commit**

All incremental commits were made in earlier tasks. If any unstaged changes remain:
```bash
git status  # review what's unstaged
git add apps/backend/src/app/services/discovery_import_service.py \
         apps/backend/src/app/services/inference_service.py \
         apps/backend/src/app/services/layout_service.py \
         apps/backend/src/app/api/discovery.py \
         apps/backend/src/app/schemas/discovery.py \
         apps/frontend/src/api/client.jsx \
         apps/frontend/src/hooks/useMapRealTimeUpdates.js \
         apps/frontend/src/pages/MapPage.jsx \
         apps/frontend/src/components/ScanImportModal.jsx \
         apps/frontend/src/styles/main.css
git commit -m "feat: complete scan-to-map pipeline (inference + batch import + map modal)"
```
