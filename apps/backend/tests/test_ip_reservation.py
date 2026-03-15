"""
Service-layer tests for IP/port conflict detection.

Tests exercise the functions in app.services.ip_reservation directly
using the db_session fixture (rolled back after each test).
"""

from app.services.ip_reservation import (
    bulk_conflict_map,
    check_ip_conflict,
    resolve_ip_conflict,
)

# ── check_ip_conflict ───────────────────────────────────────────────────────


def test_check_no_conflict_empty_db(db_session):
    """No entities in the DB means no conflicts."""
    result = check_ip_conflict(db_session, "10.0.0.1")
    assert result == []


def test_check_hardware_ip_conflict(db_session, factories):
    """Hardware with the same IP is reported as a conflict."""
    hw = factories.hardware(name="server-a", ip_address="10.0.0.1")
    result = check_ip_conflict(db_session, "10.0.0.1")
    assert len(result) >= 1
    conflict = result[0]
    assert conflict.entity_type == "hardware"
    assert conflict.entity_id == hw.id
    assert conflict.conflicting_ip == "10.0.0.1"


def test_check_excludes_self(db_session, factories):
    """The entity being edited is excluded from conflict results."""
    hw = factories.hardware(name="self-server", ip_address="10.0.0.5")
    result = check_ip_conflict(
        db_session,
        "10.0.0.5",
        exclude_entity_type="hardware",
        exclude_entity_id=hw.id,
    )
    assert len(result) == 0


def test_check_service_port_clash(db_session, factories):
    """Two services on the same IP+port+protocol collide."""
    factories.service(
        name="web-1",
        ip_address="10.0.0.10",
        ports_json=[{"port": 80, "protocol": "tcp"}],
    )
    result = check_ip_conflict(
        db_session,
        "10.0.0.10",
        ports=[{"port": 80, "protocol": "tcp"}],
        exclude_entity_type="service",
        exclude_entity_id=0,  # new entity, no existing id
    )
    assert any(c.entity_type == "service" and c.conflicting_port == 80 for c in result)


def test_check_no_conflict_different_port(db_session, factories):
    """Services on the same IP but different ports do not conflict."""
    factories.service(
        name="web-a",
        ip_address="10.0.0.20",
        ports_json=[{"port": 80, "protocol": "tcp"}],
    )
    result = check_ip_conflict(
        db_session,
        "10.0.0.20",
        ports=[{"port": 443, "protocol": "tcp"}],
        exclude_entity_type="service",
        exclude_entity_id=0,
    )
    port_conflicts = [c for c in result if c.conflicting_port is not None]
    assert len(port_conflicts) == 0


# ── resolve_ip_conflict ─────────────────────────────────────────────────────


def test_resolve_inherited_from_hardware(db_session, factories):
    """A service inheriting its IP from hardware is not a conflict."""
    hw = factories.hardware(name="host-1", ip_address="10.0.0.50")
    result = resolve_ip_conflict(
        db_session,
        service_id=None,
        ip_address="10.0.0.50",
        compute_id=None,
        hardware_id=hw.id,
    )
    assert result["is_conflict"] is False
    assert result["ip_mode"] == "inherited_from_hardware"


def test_resolve_explicit_ip_no_conflict(db_session, factories):
    """A service with an explicit IP that nobody else uses is clean."""
    result = resolve_ip_conflict(
        db_session,
        service_id=None,
        ip_address="192.168.99.99",
        compute_id=None,
        hardware_id=None,
    )
    assert result["is_conflict"] is False
    assert result["ip_mode"] == "explicit"


def test_resolve_none_ip(db_session):
    """No IP address means no conflict and ip_mode=none."""
    result = resolve_ip_conflict(
        db_session,
        service_id=None,
        ip_address=None,
        compute_id=None,
        hardware_id=None,
    )
    assert result["is_conflict"] is False
    assert result["ip_mode"] == "none"


# ── bulk_conflict_map ────────────────────────────────────────────────────────


def test_bulk_conflict_map_empty(db_session):
    """Empty DB yields an empty (or all-False) conflict map."""
    result = bulk_conflict_map(db_session)
    assert isinstance(result, dict)
    assert all(v is False for v in result.values())


def test_bulk_conflict_map_detects_hardware_ip_clash(db_session, factories):
    """Two hardware items with the same IP are flagged."""
    hw1 = factories.hardware(name="dup-hw-1", ip_address="10.0.1.1")
    hw2 = factories.hardware(name="dup-hw-2", ip_address="10.0.1.1")
    result = bulk_conflict_map(db_session)
    assert result.get(("hardware", hw1.id)) is True
    assert result.get(("hardware", hw2.id)) is True


def test_bulk_conflict_map_service_port_clash(db_session, factories):
    """Two services on the same IP:port are flagged."""
    svc1 = factories.service(
        name="svc-clash-1",
        ip_address="10.0.2.1",
        ports_json=[{"port": 8080, "protocol": "tcp"}],
    )
    svc2 = factories.service(
        name="svc-clash-2",
        ip_address="10.0.2.1",
        ports_json=[{"port": 8080, "protocol": "tcp"}],
    )
    result = bulk_conflict_map(db_session)
    assert result.get(("service", svc1.id)) is True
    assert result.get(("service", svc2.id)) is True


def test_bulk_conflict_map_no_false_positive(db_session, factories):
    """Different IPs should not conflict."""
    hw1 = factories.hardware(name="clean-1", ip_address="10.100.0.1")
    hw2 = factories.hardware(name="clean-2", ip_address="10.100.0.2")
    result = bulk_conflict_map(db_session)
    assert result.get(("hardware", hw1.id), False) is False
    assert result.get(("hardware", hw2.id), False) is False
