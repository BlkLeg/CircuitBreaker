"""Tests for Proxmox priority override of raw ICMP/TCP check outcomes."""

from datetime import UTC, datetime, timedelta

from app.core.time import utcnow
from app.services.monitoring.collectors import Sample
from app.services.monitoring.proxmox_override import apply_proxmox_overrides


def _outcome(item_id, target_type, target_id, up, avail_value, msg="", extra_samples=None):
    samples = [Sample("avail", avail_value), *(extra_samples or [])]
    row = (item_id, target_type, target_id, samples, datetime.now(UTC))
    return row, up, msg


def test_fresh_hardware_overrides_false_down(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=utcnow())
    latency = Sample("latency_ms", 1234.0)
    outcome = _outcome(
        1, "hardware", hw.id, False, 0.0, msg="100% packet loss", extra_samples=[latency]
    )
    items = [{"item_id": 1, "target_type": "hardware", "target_id": hw.id}]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is True
    samples_out = new_row[3]
    assert samples_out[0].metric == "avail" and samples_out[0].value == 1.0
    assert samples_out[1] is latency  # other samples untouched, same object
    assert "overridden" in new_msg and "node running" in new_msg


def test_stale_hardware_passes_through_unchanged(db_session, factories):
    stale = utcnow() - timedelta(minutes=10)
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=stale)
    outcome = _outcome(2, "hardware", hw.id, False, 0.0)
    items = [{"item_id": 2, "target_type": "hardware", "target_id": hw.id}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome  # untouched: same tuple object, not rebuilt


def test_hardware_without_proxmox_link_passes_through_unchanged(db_session, factories):
    hw = factories.hardware()
    outcome = _outcome(3, "hardware", hw.id, False, 0.0)
    items = [{"item_id": 3, "target_type": "hardware", "target_id": hw.id}]

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
    items = [{"item_id": 4, "target_type": "compute_unit", "target_id": cu.id}]

    [(new_row, new_up, new_msg)] = apply_proxmox_overrides(db_session, items, [outcome])

    assert new_up is False
    assert new_row[3][0].value == 0.0
    assert "overridden" in new_msg and "stopped" in new_msg


def test_agreement_passes_through_unchanged(db_session, factories):
    hw = factories.hardware(proxmox_node_name="pve1", telemetry_last_polled=utcnow())
    outcome = _outcome(5, "hardware", hw.id, True, 1.0)
    items = [{"item_id": 5, "target_type": "hardware", "target_id": hw.id}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_missing_target_row_passes_through_unchanged(db_session):
    outcome = _outcome(6, "hardware", 999999, False, 0.0)
    items = [{"item_id": 6, "target_type": "hardware", "target_id": 999999}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome


def test_standalone_monitor_passes_through_unchanged(db_session):
    outcome = _outcome(7, None, None, False, 0.0)
    items = [{"item_id": 7, "target_type": None, "target_id": None}]

    [result] = apply_proxmox_overrides(db_session, items, [outcome])

    assert result is outcome
