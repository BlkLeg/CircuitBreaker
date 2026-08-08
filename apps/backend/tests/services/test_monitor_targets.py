"""Target-scoped monitors: resolver defaults, idempotency, and rollups."""

import json

import pytest

from app.db.models import ComputeUnit, ExternalNode, Hardware, Service
from app.services import monitor_service


def _hardware(db, **overrides):
    fields = {"name": "nas01", "role": "nas", "ip_address": "192.0.2.10"}
    fields.update(overrides)
    hw = Hardware(**fields)
    db.add(hw)
    db.commit()
    db.refresh(hw)
    return hw


def _compute_unit(db, hardware_id, **overrides):
    fields = {
        "name": "web-vm",
        "kind": "vm",
        "hardware_id": hardware_id,
        "ip_address": "192.0.2.20",
    }
    fields.update(overrides)
    cu = ComputeUnit(**fields)
    db.add(cu)
    db.commit()
    db.refresh(cu)
    return cu


def _external_node(db, **overrides):
    fields = {
        "name": "hetzner-vps",
        "provider": "Hetzner",
        "kind": "vps",
        "ip_address": "192.0.2.40",
    }
    fields.update(overrides)
    node = ExternalNode(**fields)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


def _service(db, slug, **overrides):
    fields = {"name": slug, "slug": slug}
    fields.update(overrides)
    svc = Service(**fields)
    db.add(svc)
    db.commit()
    db.refresh(svc)
    return svc


# ── Resolver defaults per target type ────────────────────────────────────────


def test_hardware_resolves_to_icmp(db_session):
    hw = _hardware(db_session)
    mon = monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    assert mon["check_type"] == "icmp"
    assert mon["host"] == "192.0.2.10"
    assert mon["config"] == {"packet_count": 5}
    assert mon["target_type"] == "hardware"
    assert mon["target_id"] == hw.id


def test_hardware_falls_back_to_hostname(db_session):
    hw = _hardware(db_session, name="edge", ip_address=None, hostname="edge.lan")
    mon = monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    assert mon["host"] == "edge.lan"


def test_compute_unit_resolves_to_icmp(db_session):
    hw = _hardware(db_session)
    cu = _compute_unit(db_session, hw.id)
    mon = monitor_service.create_target_monitor(db_session, "compute_unit", cu.id)
    assert mon["check_type"] == "icmp"
    assert mon["host"] == "192.0.2.20"
    assert mon["target_type"] == "compute_unit"


def test_service_with_url_resolves_to_http(db_session):
    svc = _service(db_session, "grafana", url="https://grafana.lan:3000/login")
    mon = monitor_service.create_target_monitor(db_session, "service", svc.id)
    assert mon["check_type"] == "http"
    assert mon["host"] == "grafana.lan"
    assert mon["config"] == {"url": "https://grafana.lan:3000/login"}


def test_service_with_ports_json_resolves_to_tcp(db_session):
    svc = _service(
        db_session,
        "postgres",
        ip_address="192.0.2.30",
        ports_json=json.dumps([{"port": 5432, "protocol": "tcp"}]),
    )
    mon = monitor_service.create_target_monitor(db_session, "service", svc.id)
    assert mon["check_type"] == "tcp"
    assert mon["host"] == "192.0.2.30"
    assert mon["config"] == {"port": 5432}


def test_service_with_free_text_ports_resolves_to_tcp(db_session):
    svc = _service(db_session, "redis", ip_address="192.0.2.31", ports="6379/tcp, 16379")
    mon = monitor_service.create_target_monitor(db_session, "service", svc.id)
    assert mon["check_type"] == "tcp"
    assert mon["config"] == {"port": 6379}


def test_external_node_resolves_to_icmp(db_session):
    node = _external_node(db_session)
    mon = monitor_service.create_target_monitor(db_session, "external_node", node.id)
    assert mon["check_type"] == "icmp"
    assert mon["host"] == "192.0.2.40"
    assert mon["target_type"] == "external_node"
    assert mon["target_id"] == node.id


def test_external_node_accepts_a_hostname(db_session):
    node = _external_node(db_session, name="api", ip_address="api.example.com")
    mon = monitor_service.create_target_monitor(db_session, "external_node", node.id)
    assert mon["host"] == "api.example.com"


def test_service_with_ip_only_resolves_to_icmp(db_session):
    svc = _service(db_session, "bare", ip_address="192.0.2.32")
    mon = monitor_service.create_target_monitor(db_session, "service", svc.id)
    assert mon["check_type"] == "icmp"


# ── Unprobeable / unknown targets ────────────────────────────────────────────


@pytest.mark.parametrize("target_type", ["hardware", "compute_unit", "service", "external_node"])
def test_unknown_target_returns_none(db_session, target_type):
    assert monitor_service.create_target_monitor(db_session, target_type, 999_999) is None


def test_target_with_no_address_returns_none(db_session):
    hw = _hardware(db_session, name="ghost", ip_address=None, hostname=None)
    cu = _compute_unit(db_session, hw.id, name="no-ip-ct", kind="container", ip_address=None)
    svc = _service(db_session, "no-addr")
    node = _external_node(db_session, name="saas-only", kind="saas", ip_address=None)
    assert monitor_service.create_target_monitor(db_session, "hardware", hw.id) is None
    assert monitor_service.create_target_monitor(db_session, "compute_unit", cu.id) is None
    assert monitor_service.create_target_monitor(db_session, "service", svc.id) is None
    assert monitor_service.create_target_monitor(db_session, "external_node", node.id) is None


def test_unsupported_target_type_returns_none(db_session):
    assert monitor_service.resolve_target(db_session, "ip", 1) is None
    assert monitor_service.create_target_monitor(db_session, "ip", 1) is None


# ── Idempotency and overrides ────────────────────────────────────────────────


def test_create_is_idempotent_per_check_type(db_session):
    hw = _hardware(db_session)
    first = monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    second = monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    assert first["id"] == second["id"]
    assert len(monitor_service.list_monitors(db_session, target_type="hardware")) == 1


def test_explicit_check_type_creates_a_second_monitor(db_session):
    hw = _hardware(db_session)
    icmp = monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    tcp = monitor_service.create_target_monitor(
        db_session, "hardware", hw.id, check_type="tcp", config={"port": 443}
    )
    assert icmp["id"] != tcp["id"]
    assert tcp["config"] == {"port": 443}
    # A non-default check type must not inherit the resolver's icmp config.
    bare = monitor_service.create_target_monitor(db_session, "hardware", hw.id, check_type="dns")
    assert bare["config"] == {}


def test_invalid_config_override_raises(db_session):
    hw = _hardware(db_session)
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
        monitor_service.create_target_monitor(
            db_session, "hardware", hw.id, check_type="tcp", config={"bogus": 1}
        )


# ── Pause / resume / check ───────────────────────────────────────────────────


def test_pause_and_resume_target(db_session):
    hw = _hardware(db_session)
    monitor_service.create_target_monitor(db_session, "hardware", hw.id)

    assert monitor_service.set_target_paused(db_session, "hardware", hw.id, True) is True
    assert monitor_service.list_monitors(db_session, target_type="hardware")[0]["enabled"] is False

    assert monitor_service.set_target_paused(db_session, "hardware", hw.id, False) is True
    assert monitor_service.list_monitors(db_session, target_type="hardware")[0]["enabled"] is True


async def test_pause_unmonitored_target_returns_false(db_session):
    hw = _hardware(db_session)
    assert monitor_service.set_target_paused(db_session, "hardware", hw.id, True) is False
    assert await monitor_service.run_target_check(db_session, "hardware", hw.id) is False


async def test_target_check_publishes_one_message_per_vantage(db_session, factories, monkeypatch):
    """A target with both vantages on it: the server monitor goes to the poll
    subject, the assigned one gets a run and its id goes to the probe subject.
    Neither may be silently dropped — the assigned one especially, because the
    run it opens holds the active-run index until something dispatches it."""
    from app.core.nats_client import nats_client
    from app.core.subjects import MONITOR_POLL_ITEM, MONITOR_PROBE_REMOTE
    from app.db.models import MonitorProbeRun

    published: list[tuple[str, dict]] = []

    async def _publish(subject, payload):
        published.append((subject, payload))
        return True

    monkeypatch.setattr(nats_client, "js_publish", _publish)

    agent = factories.agent(status="active")
    hw = _hardware(db_session)
    server_monitor = monitor_service._build_target_monitor(db_session, "hardware", hw.id)
    agent_monitor = monitor_service._build_target_monitor(
        db_session, "hardware", hw.id, check_type="tcp", config={"port": 22}
    )
    agent_monitor.probe_agent_id = agent.id
    db_session.commit()

    assert await monitor_service.run_target_check(db_session, "hardware", hw.id) is True

    run = (
        db_session.query(MonitorProbeRun)
        .filter(MonitorProbeRun.monitor_id == agent_monitor.id)
        .one()
    )
    assert run.status == "queued"
    assert published == [
        (MONITOR_POLL_ITEM, monitor_service._poll_payload(server_monitor)),
        (MONITOR_PROBE_REMOTE, {"run_id": run.run_id}),
    ]


# ── Summaries ────────────────────────────────────────────────────────────────


def test_target_summary_shape_and_filtering(db_session):
    hw = _hardware(db_session)
    cu = _compute_unit(db_session, hw.id)
    other = _compute_unit(db_session, hw.id, name="other-vm", ip_address="192.0.2.21")
    monitor_service.create_target_monitor(db_session, "compute_unit", cu.id)
    monitor_service.create_target_monitor(db_session, "compute_unit", other.id)

    all_rows = monitor_service.list_target_summaries(db_session, "compute_unit")
    assert {r["target_id"] for r in all_rows} == {cu.id, other.id}

    row = next(r for r in all_rows if r["target_id"] == cu.id)
    assert row["target_type"] == "compute_unit"
    assert row["enabled"] is True
    assert row["status"] == "pending"
    assert row["monitor_ids"] == [row["monitor_id"]]

    filtered = monitor_service.list_target_summaries(db_session, "compute_unit", [cu.id])
    assert [r["target_id"] for r in filtered] == [cu.id]
    assert monitor_service.list_target_summaries(db_session, "compute_unit", []) == []
    assert monitor_service.list_target_summaries(db_session, "hardware") == []


def test_target_summary_aggregates_worst_status(db_session):
    hw = _hardware(db_session)
    monitor_service.create_target_monitor(db_session, "hardware", hw.id)
    monitor_service.create_target_monitor(db_session, "hardware", hw.id, check_type="tcp")

    items = monitor_service._target_monitors(db_session, "hardware", hw.id)
    items[0].last_status = "up"
    items[1].last_status = "down"
    db_session.commit()

    row = monitor_service.list_target_summaries(db_session, "hardware")[0]
    assert row["status"] == "down"
    assert len(row["monitor_ids"]) == 2
    assert row["monitor_id"] == items[0].id


# ── Discovery auto-monitor shares the same builder ───────────────────────────


def test_build_target_monitor_defers_the_commit(db_session):
    """discovery_merge builds inside its own transaction, so the builder must not commit."""
    hw = _hardware(db_session)
    item = monitor_service._build_target_monitor(db_session, "hardware", hw.id)
    assert item is not None and item.id is not None  # flushed, id assigned
    db_session.rollback()
    assert monitor_service.list_target_summaries(db_session, "hardware") == []
