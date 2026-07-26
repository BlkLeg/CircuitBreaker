"""Tests for Proxmox priority override of raw ICMP/TCP check outcomes."""

import logging
from datetime import UTC, datetime, timedelta

from app.core.time import utcnow
from app.services.monitoring.collectors import Sample
from app.services.monitoring.proxmox_override import apply_proxmox_overrides


def _outcome(item_id, target_type, target_id, up, avail_value, msg="", extra_samples=None):
    samples = [Sample("avail", avail_value), *(extra_samples or [])]
    row = (item_id, target_type, target_id, samples, datetime.now(UTC))
    return row, up, msg


def _item(item_id, target_type, target_id, check_type="icmp"):
    return {
        "item_id": item_id,
        "target_type": target_type,
        "target_id": target_id,
        "check_type": check_type,
    }


def test_fresh_hardware_overrides_false_down(db_session, factories):
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="healthy"
    )
    latency = Sample("latency_ms", 1234.0)
    outcome = _outcome(
        1, "hardware", hw.id, False, 0.0, msg="100% packet loss", extra_samples=[latency]
    )
    items = [_item(1, "hardware", hw.id)]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is True
    samples_out = new_row[3]
    assert samples_out[0].metric == "avail" and samples_out[0].value == 1.0
    assert samples_out[1] is latency  # other samples untouched, same object
    assert "overridden" in new_msg and "node running" in new_msg


def test_fresh_but_non_live_hardware_passes_through_unchanged(db_session, factories):
    """A fresh telemetry_last_polled is not sufficient on its own — discovery
    and telemetry-ingest paths stamp it unconditionally even for offline
    nodes. telemetry_status must also indicate a live poll."""
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="unknown"
    )
    outcome = _outcome(101, "hardware", hw.id, False, 0.0, msg="100% packet loss")
    items = [_item(101, "hardware", hw.id)]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome  # untouched: same tuple object, not rebuilt


def test_stale_hardware_passes_through_unchanged(db_session, factories):
    stale = utcnow() - timedelta(minutes=10)
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=stale, telemetry_status="healthy"
    )
    outcome = _outcome(2, "hardware", hw.id, False, 0.0)
    items = [_item(2, "hardware", hw.id)]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome  # untouched: same tuple object, not rebuilt


def test_hardware_without_proxmox_link_passes_through_unchanged(db_session, factories):
    hw = factories.hardware()
    outcome = _outcome(3, "hardware", hw.id, False, 0.0)
    items = [_item(3, "hardware", hw.id)]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_fresh_compute_unit_overrides_false_up(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1")
    cu = factories.compute_unit(
        hardware_id=hw.id,
        proxmox_vmid=100,
        status="inactive",
        telemetry_last_polled=utcnow(),
    )
    outcome = _outcome(4, "compute_unit", cu.id, True, 1.0, msg="tcp connect ok")
    items = [_item(4, "compute_unit", cu.id, check_type="tcp")]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is False
    assert new_row[3][0].value == 0.0
    assert "overridden" in new_msg and "stopped" in new_msg


def test_agreement_passes_through_unchanged(db_session, factories):
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="healthy"
    )
    outcome = _outcome(5, "hardware", hw.id, True, 1.0)
    items = [_item(5, "hardware", hw.id)]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_missing_target_row_passes_through_unchanged(db_session):
    outcome = _outcome(6, "hardware", 999999, False, 0.0)
    items = [_item(6, "hardware", 999999)]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_standalone_monitor_passes_through_unchanged(db_session):
    outcome = _outcome(7, None, None, False, 0.0)
    items = [{"item_id": 7, "target_type": None, "target_id": None, "check_type": "icmp"}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_non_icmp_tcp_check_type_not_overridden(db_session, factories):
    """The override is only evidence about whether the node/VM is running,
    not about an application-level service on top of it — so http/dns
    checks must never be overridden, even with a fresh, disagreeing,
    genuinely-live Proxmox opinion."""
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="healthy"
    )
    outcome = _outcome(102, "hardware", hw.id, False, 0.0, msg="http 500")
    items = [_item(102, "hardware", hw.id, check_type="http")]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome  # untouched: same tuple object, not rebuilt


def test_dns_check_type_not_overridden(db_session, factories):
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="healthy"
    )
    outcome = _outcome(103, "hardware", hw.id, False, 0.0, msg="dns nxdomain")
    items = [_item(103, "hardware", hw.id, check_type="dns")]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_override_logs_when_applied(db_session, factories, caplog):
    """Even when no state-transition event fires (so nothing gets persisted
    to the events log), the override must leave a trace via logging rather
    than silently discarding the annotated message."""
    hw = factories.hardware(
        proxmox_node_name="pve1", telemetry_last_polled=utcnow(), telemetry_status="healthy"
    )
    outcome = _outcome(104, "hardware", hw.id, False, 0.0, msg="100% packet loss")
    items = [_item(104, "hardware", hw.id)]

    with caplog.at_level(logging.INFO, logger="app.services.monitoring.proxmox_override"):
        apply_proxmox_overrides(db_session, items, [outcome])

    assert any("Proxmox override" in r.message and "104" in r.message for r in caplog.records)
