"""`app.services.telemetry_normalize` — the one place a normalized platform
telemetry dict is mapped onto `HardwareLiveMetric` columns.

Task 5 of `plans/2026-08-06-cbi-agent-slice12-cohesion-hardening-tasks.md`
collapses three copies of that mapping (`telemetry_service.write_telemetry`,
`telemetry_ingest_worker._build_metric_row`, and the agent projection in
`agent_telemetry.ingest_host_sample`) into `live_metric_fields`. The parity
tests below are the refactor's safety net: they pin the *poller* column values
that must not move, so slices 3 and 4 can import the same function instead of
adding a fourth copy.
"""

from __future__ import annotations

import pytest

from app.services.telemetry_normalize import (
    _NON_LIVE_STATUSES,
    agent_summary_to_platform,
    live_metric_fields,
)
from app.workers.telemetry_ingest_worker import _build_metric_row

# Exactly the numeric/derived columns on `hardware_live_metrics`; the
# attribution columns (hardware_id, collected_at, status, source, raw,
# error_msg, agent_*) are the caller's business, never the normalizer's.
_LIVE_METRIC_COLUMNS = {
    "cpu_pct",
    "mem_pct",
    "mem_used_mb",
    "mem_total_mb",
    "disk_pct",
    "temp_c",
    "power_w",
    "uptime_s",
}

# A poller-shaped payload using every *alias* key the legacy expressions
# accepted (`cpu`, `mem_used`, `mem_total`, `cpu_temp`, `system_power_w`,
# `uptime`) so the fallback half of each `or` is exercised.
_POLLER_PAYLOAD = {
    "cpu": 12.5,
    "mem_used": 5368709632,
    "mem_total": 16637792256,
    "cpu_temp": 48.0,
    "system_power_w": 42.5,
    "uptime": 864000.25,
    "rootfs_used": 209045065728,
    "rootfs_total": 500107862016,
}

_POLLER_COLUMNS = {
    "cpu_pct": 12.5,
    "mem_pct": 32.27,
    "mem_used_mb": 5120.0,
    "mem_total_mb": 15867.04,
    "disk_pct": 41.8,
    "temp_c": 48.0,
    "power_w": 42.5,
    "uptime_s": 864000,
}


def test_live_metric_fields_returns_exactly_the_metric_columns():
    assert set(live_metric_fields(_POLLER_PAYLOAD)) == _LIVE_METRIC_COLUMNS


def test_live_metric_fields_matches_the_legacy_poller_mapping():
    """Byte-identical column values for a poller-shaped payload."""
    assert live_metric_fields(_POLLER_PAYLOAD) == _POLLER_COLUMNS


def test_live_metric_fields_prefers_canonical_keys_over_aliases():
    data = dict(_POLLER_PAYLOAD, cpu_pct=90.0, temp_c=70.0, power_w=5.0, uptime_s=10)
    fields = live_metric_fields(data)
    assert fields["cpu_pct"] == 90.0
    assert fields["temp_c"] == 70.0
    assert fields["power_w"] == 5.0
    assert fields["uptime_s"] == 10


def test_live_metric_fields_omits_nothing_and_nulls_absent_sources():
    assert live_metric_fields({}) == dict.fromkeys(_LIVE_METRIC_COLUMNS, None)


def test_ingest_worker_row_is_built_from_live_metric_fields():
    """The worker path and the normalizer cannot drift apart."""
    row = _build_metric_row(7, "snmp", _POLLER_PAYLOAD, "ok", None, "2026-01-01T00:00:00Z")
    assert {k: row[k] for k in _LIVE_METRIC_COLUMNS} == _POLLER_COLUMNS
    assert row["hardware_id"] == 7
    assert row["source"] == "snmp"
    assert row["raw"] is _POLLER_PAYLOAD


def test_non_live_statuses_are_re_exported_from_telemetry_service():
    """`monitoring/proxmox_override.py` imports the set from its old home."""
    from app.services import telemetry_service

    assert telemetry_service._NON_LIVE_STATUSES is _NON_LIVE_STATUSES
    assert _NON_LIVE_STATUSES == {"unknown", "unreachable", "error", "unconfigured"}


# ── agent summary -> platform dict ───────────────────────────────────────────

_AGENT_SUMMARY = {
    "cpu_pct": 12.5,
    "mem_pct": 32.27,
    "mem_total_bytes": 16637792256,
    "mem_used_bytes": 5368709632,
    "mem_available_bytes": 10737418240,
    "swap_total_bytes": 2147483648,
    "swap_used_bytes": 268435456,
    "swap_pct": 12.5,
    "root_disk_pct": 41.8,
    "net_rx_bps": 15234.75,
    "net_tx_bps": 8321.5,
    "max_temp_c": 48.0,
    "uptime_s": 864000.25,
    "load_1": 0.42,
    "load_5": 0.37,
    "load_15": 0.29,
    "logical_cpus": 8,
    "boot_time_unix_s": 1753617600,
}

_FILESYSTEMS = [
    {"device": "tmpfs", "mountpoint": "/run", "total_bytes": 1, "used_bytes": 1},
    {
        "device": "/dev/nvme0n1p2",
        "mountpoint": "/",
        "total_bytes": 500107862016,
        "used_bytes": 209045065728,
        "available_bytes": 265527754752,
        "used_pct": 41.8,
    },
]


def test_agent_summary_to_platform_emits_platform_key_names():
    platform = agent_summary_to_platform(_AGENT_SUMMARY, _FILESYSTEMS)

    assert platform["cpu_pct"] == 12.5
    assert platform["mem_pct"] == 32.27
    assert platform["mem_used"] == 5368709632
    assert platform["mem_total"] == 16637792256
    assert platform["mem_used_mb"] == 5120.0
    assert platform["mem_total_mb"] == 15867.04
    assert platform["mem_used_gb"] == 5.0
    assert platform["mem_total_gb"] == 15.5
    assert platform["disk_pct"] == 41.8
    assert platform["rootfs_used"] == 209045065728
    assert platform["rootfs_total"] == 500107862016
    assert platform["disk_used_gb"] == 194.7
    assert platform["disk_total_gb"] == 465.8
    assert platform["temp_c"] == 48.0
    assert platform["cpu_temp"] == 48.0
    assert platform["uptime_s"] == 864000


def test_agent_summary_to_platform_drops_agent_key_names():
    platform = agent_summary_to_platform(_AGENT_SUMMARY, _FILESYSTEMS)

    assert "root_disk_pct" not in platform
    assert "max_temp_c" not in platform
    assert "mem_used_bytes" not in platform
    assert "mem_total_bytes" not in platform


@pytest.mark.parametrize(
    "key",
    [
        "load_1",
        "load_5",
        "load_15",
        "logical_cpus",
        "mem_available_bytes",
        "swap_pct",
        "swap_used_bytes",
        "swap_total_bytes",
        "net_rx_bps",
        "net_tx_bps",
        "boot_time_unix_s",
    ],
)
def test_agent_summary_to_platform_passes_agent_detail_fields_through(key):
    platform = agent_summary_to_platform(_AGENT_SUMMARY, _FILESYSTEMS)
    assert platform[key] == _AGENT_SUMMARY[key]


def test_agent_summary_to_platform_never_fabricates_power():
    """The Linux collector has no power probe; `power_w` must stay NULL so the
    map node's wattage badge correctly renders nothing."""
    platform = agent_summary_to_platform(_AGENT_SUMMARY, _FILESYSTEMS)

    assert "power_w" not in platform
    assert "system_power_w" not in platform
    assert live_metric_fields(platform)["power_w"] is None


def test_agent_summary_to_platform_omits_absent_keys_rather_than_nulling_them():
    """Omission (not `None`) is what keeps the `_derive_*` fallbacks working."""
    platform = agent_summary_to_platform({"cpu_pct": 3.0, "mem_pct": 61.25}, [])

    assert platform == {"cpu_pct": 3.0, "mem_pct": 61.25}
    assert live_metric_fields(platform)["disk_pct"] is None


def test_agent_summary_to_platform_ignores_non_root_filesystems():
    platform = agent_summary_to_platform(
        _AGENT_SUMMARY, [{"mountpoint": "/boot", "total_bytes": 5, "used_bytes": 1}]
    )

    assert "rootfs_used" not in platform
    assert "disk_used_gb" not in platform
    # root_disk_pct still supplies disk_pct without any filesystem entry.
    assert platform["disk_pct"] == 41.8


def test_agent_platform_dict_feeds_live_metric_fields_like_the_poller():
    """The agent projection and the poller projection agree column-for-column."""
    platform = agent_summary_to_platform(_AGENT_SUMMARY, _FILESYSTEMS)

    assert live_metric_fields(platform) == {
        "cpu_pct": 12.5,
        "mem_pct": 32.27,
        "mem_used_mb": 5120.0,
        "mem_total_mb": 15867.04,
        "disk_pct": 41.8,
        "temp_c": 48.0,
        "power_w": None,
        "uptime_s": 864000,
    }


def test_zero_valued_metrics_survive_the_alias_fallbacks():
    """An idle host reporting exactly 0.0 must persist 0.0, not NULL.

    The alias chains are presence-based, not truthiness-based: the agent
    projection this module absorbed wrote `cpu_pct=row.cpu_pct` directly, so a
    `data.get("cpu_pct") or data.get("cpu")` would have silently turned a real
    0.0 reading into NULL once the legacy alias is absent.
    """
    fields = live_metric_fields(
        {
            "cpu_pct": 0.0,
            "mem_pct": 0.0,
            "mem_used_mb": 0.0,
            "mem_total_mb": 0.0,
            "disk_pct": 0.0,
            "temp_c": 0.0,
            "power_w": 0.0,
            "uptime_s": 0,
        }
    )

    assert fields == {
        "cpu_pct": 0.0,
        "mem_pct": 0.0,
        "mem_used_mb": 0.0,
        "mem_total_mb": 0.0,
        "disk_pct": 0.0,
        "temp_c": 0.0,
        "power_w": 0.0,
        "uptime_s": 0,
    }


def test_alias_fallback_still_applies_when_the_primary_key_is_absent():
    """Presence-based lookup must not break the legacy poller alias names."""
    fields = live_metric_fields(
        {"cpu": 7.5, "cpu_temp": 41.0, "system_power_w": 90.0, "uptime": 42}
    )

    assert fields["cpu_pct"] == 7.5
    assert fields["temp_c"] == 41.0
    assert fields["power_w"] == 90.0
    assert fields["uptime_s"] == 42
