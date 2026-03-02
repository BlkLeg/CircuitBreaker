"""Feature 3 — IP/Port reservation tests."""
import json

from app.db.models import Service
from app.core.time import utcnow


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hw(client, name="pve-01", ip="10.0.0.1"):
    return client.post("/api/v1/hardware", json={"name": name, "ip_address": ip})


def _cu(client, name="vm-01", ip="10.0.0.2"):
    hw = client.post("/api/v1/hardware", json={"name": f"host-for-{name}"}).json()
    return client.post("/api/v1/compute-units", json={
        "name": name, "kind": "vm", "hardware_id": hw["id"], "ip_address": ip,
    })


def _svc(client, name="Plex", ip="10.0.0.5", ports=None):
    payload = {"name": name, "slug": name.lower().replace(" ", "-"), "ip_address": ip}
    if ports:
        payload["ports"] = ports
    return client.post("/api/v1/services", json=payload)


def _ip_check(client, ip, ports=None, exclude_type=None, exclude_id=None):
    payload = {"ip": ip}
    if ports:
        payload["ports"] = ports
    if exclude_type:
        payload["exclude_entity_type"] = exclude_type
    if exclude_id:
        payload["exclude_entity_id"] = exclude_id
    return client.post("/api/v1/ip-check", json=payload)


# ── Basic IP conflict ─────────────────────────────────────────────────────────

def test_no_conflict_on_unique_ip(client):
    resp = _hw(client, name="pve-01", ip="10.0.0.1")
    assert resp.status_code == 201


def test_hardware_ip_conflict_with_hardware(client):
    _hw(client, name="pve-01", ip="10.0.0.1")
    resp = _hw(client, name="pve-02", ip="10.0.0.1")
    assert resp.status_code == 409
    conflicts = resp.json().get("detail", {}).get("conflicts", [])
    assert any(c["entity_type"] == "hardware" for c in conflicts)


def test_hardware_ip_conflict_with_compute_unit(client):
    _cu(client, name="vm-01", ip="10.0.0.2")
    resp = _hw(client, name="pve-01", ip="10.0.0.2")
    assert resp.status_code == 409


# ── Service port conflict ─────────────────────────────────────────────────────

def test_service_port_conflict(client):
    _svc(client, name="ServiceA", ip="10.0.0.5",
         ports=[{"port": 8080, "protocol": "tcp"}])
    resp = _svc(client, name="ServiceB", ip="10.0.0.5",
                ports=[{"port": 8080, "protocol": "tcp"}])
    assert resp.status_code == 409
    conflicts = resp.json().get("detail", {}).get("conflicts", [])
    assert any(c.get("conflicting_port") == 8080 for c in conflicts)


def test_service_different_port_no_conflict(client):
    _svc(client, name="ServiceA", ip="10.0.0.5",
         ports=[{"port": 8080, "protocol": "tcp"}])
    resp = _svc(client, name="ServiceB", ip="10.0.0.5",
                ports=[{"port": 9090, "protocol": "tcp"}])
    assert resp.status_code == 201


def test_service_different_protocol_no_conflict(client):
    _svc(client, name="ServiceA", ip="10.0.0.5",
         ports=[{"port": 53, "protocol": "tcp"}])
    resp = _svc(client, name="ServiceB", ip="10.0.0.5",
                ports=[{"port": 53, "protocol": "udp"}])
    assert resp.status_code == 201


# ── Self-edit ─────────────────────────────────────────────────────────────────

def test_edit_own_ip_no_self_conflict(client):
    hw = _hw(client, name="pve-01", ip="10.0.0.1").json()
    resp = client.patch(f"/api/v1/hardware/{hw['id']}", json={"ip_address": "10.0.0.1"})
    assert resp.status_code == 200


# ── Multiple conflicts ────────────────────────────────────────────────────────

def test_multiple_conflicts_returned(client):
    _hw(client, name="pve-01", ip="10.0.0.5")
    _svc(client, name="ServiceA", ip="10.0.0.5",
         ports=[{"port": 8080, "protocol": "tcp"}])

    # New service with same IP and same port — should conflict with both hw and ServiceA
    resp = _svc(client, name="ServiceB", ip="10.0.0.5",
                ports=[{"port": 8080, "protocol": "tcp"}])
    assert resp.status_code == 409
    conflicts = resp.json().get("detail", {}).get("conflicts", [])
    assert len(conflicts) >= 2


# ── /ip-check endpoint ────────────────────────────────────────────────────────

def test_ip_check_endpoint_clean(client):
    resp = _ip_check(client, ip="10.0.0.99")
    assert resp.status_code == 200
    assert resp.json()["conflicts"] == []


def test_ip_check_endpoint_conflict(client):
    _hw(client, name="pve-01", ip="10.0.0.1")
    resp = _ip_check(client, ip="10.0.0.1")
    assert resp.status_code == 200
    conflicts = resp.json()["conflicts"]
    assert len(conflicts) > 0
    assert conflicts[0]["conflicting_ip"] == "10.0.0.1"


# ── Ports backfill ────────────────────────────────────────────────────────────

def test_ports_backfill_from_string(db):
    """Service with legacy ports string → ports_json should be structured."""
    svc = Service(
        name="web",
        slug="web",
        ports="80/tcp,443/tcp",
        ports_json=None,
        created_at=utcnow(),
    )
    db.add(svc)
    db.flush()

    # Run the backfill logic from misc_service or services_service
    from app.services.services_service import _backfill_ports_json  # noqa
    _backfill_ports_json(db)
    db.refresh(svc)

    assert svc.ports_json is not None
    parsed = json.loads(svc.ports_json)
    assert isinstance(parsed, list)
    ports_found = [p["port"] for p in parsed]
    assert 80 in ports_found
    assert 443 in ports_found


def test_ports_backfill_unrecognised_format(db):
    """Service with unrecognised ports string → preserved in ports_json."""
    svc = Service(
        name="custom",
        slug="custom",
        ports="custom-binding",
        ports_json=None,
        created_at=utcnow(),
    )
    db.add(svc)
    db.flush()

    from app.services.services_service import _backfill_ports_json  # noqa
    _backfill_ports_json(db)
    db.refresh(svc)

    # ports_json should still be set (either raw or preserved)
    assert svc.ports_json is not None


# ── Conflict log entry ────────────────────────────────────────────────────────

def test_conflict_log_entry(client):
    _hw(client, name="pve-01", ip="10.0.0.1")
    _hw(client, name="pve-02", ip="10.0.0.1")  # triggers 409

    logs = client.get("/api/v1/logs").json()["logs"]
    conflict_entry = next(
        (log for log in logs if "conflict" in (log.get("action") or "")),
        None,
    )
    # Either a specific conflict action or a warn-severity entry referencing the IP
    warn_entry = next(
        (log for log in logs if log.get("severity") == "warn" and "10.0.0.1" in (log.get("details") or ""
         or log.get("entity_name") or "")),
        None,
    )
    assert conflict_entry is not None or warn_entry is not None, \
        "Expected a conflict or warn log entry after a 409 IP conflict"
