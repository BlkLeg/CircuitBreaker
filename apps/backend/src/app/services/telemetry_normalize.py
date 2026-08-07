"""The single home for platform telemetry normalization.

Every path that writes `hardware_live_metrics` — the synchronous poller write
(`app/services/telemetry_service.py`), the JetStream ingest worker
(`app/workers/telemetry_ingest_worker.py`), and the agent host-sample
projection (`app/services/agent_telemetry.py`) — maps its input onto the metric
columns through :func:`live_metric_fields` and nothing else. Slice 3's
`probe.result` and slice 4's `discovery.finding` projections import the same
function; a fourth copy of this mapping is a defect, not a shortcut.

Two vocabularies meet here:

* the **platform** dict — the key names every telemetry consumer already reads
  (`cpu_pct`, `mem_used`/`mem_total` in bytes, `mem_used_gb`, `disk_pct`,
  `rootfs_used`, `temp_c`/`cpu_temp`, `uptime_s`). It is what lands in
  `Hardware.telemetry_data`, `HardwareLiveMetric.raw`, and the Redis
  cache/WebSocket envelope, and therefore what the map node and telemetry
  sidebar render.
* the **agent summary** — the Go collector's own names (`root_disk_pct`,
  `max_temp_c`, `mem_used_bytes`), which stay confined to `agent_host_samples`
  and the Agent-detail API. :func:`agent_summary_to_platform` is the one
  translation between the two; it is kept separate from
  :func:`live_metric_fields` so slice 3/4 collectors can reuse the column
  mapping without inheriting host-specific `filesystems` handling.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# A status in this set means "we have no live reading", so `Hardware.last_seen`
# must not advance. Re-exported from `app.services.telemetry_service` for the
# existing importers.
_NON_LIVE_STATUSES = {"unknown", "unreachable", "error", "unconfigured"}

_MIB = 1024 * 1024
_GIB = 1024 * 1024 * 1024
_ROOT_MOUNTPOINT = "/"

# Agent summary keys the Agent-detail surfaces already render and that the
# platform dict carries through verbatim — same name, same unit, no derivation.
_AGENT_PASSTHROUGH_KEYS = (
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
)


def _first_present(data: Mapping[str, Any], *keys: str) -> Any:
    """The value of the first key that is present with a non-None value.

    Deliberately presence-based, not truthiness-based. A plain
    ``data.get("cpu_pct") or data.get("cpu")`` collapses a legitimate ``0.0``
    into the legacy alias — and, when the alias is absent, into ``None``. The
    agent projection this module absorbed wrote ``cpu_pct=row.cpu_pct``
    directly, so an idle host reporting exactly ``0.0`` used to persist ``0.0``;
    truthiness would silently turn that into NULL. The two orderings differ only
    when the primary key is present and falsy, which is precisely the case the
    old expression got wrong.
    """
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bytes_to_mb(value: Any) -> float | None:
    f = _as_float(value)
    if f is None:
        return None
    return round(f / _MIB, 2)


def _bytes_to_gb(value: Any) -> float | None:
    f = _as_float(value)
    if f is None:
        return None
    return round(f / _GIB, 1)


def _derive_mem_pct(data: Mapping[str, Any]) -> float | None:
    mem_pct = _as_float(data.get("mem_pct"))
    if mem_pct is not None:
        return mem_pct
    used = _as_float(data.get("mem_used"))
    total = _as_float(data.get("mem_total"))
    if used is None or total is None or total == 0:
        return None
    return round((used / total) * 100.0, 2)


def _derive_disk_pct(data: Mapping[str, Any]) -> float | None:
    disk_pct = _as_float(data.get("disk_pct"))
    if disk_pct is not None:
        return disk_pct
    used = _as_float(_first_present(data, "rootfs_used", "disk_used_bytes"))
    total = _as_float(_first_present(data, "rootfs_total", "disk_total_bytes"))
    if used is None or total is None or total == 0:
        return None
    return round((used / total) * 100.0, 2)


def _normalise_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str, str | None]:
    raw_data = payload.get("data")
    data: dict[str, Any]
    if isinstance(raw_data, dict):
        data = raw_data
    else:
        data = {
            k: v
            for k, v in payload.items()
            if k not in {"status", "error", "error_msg", "last_polled", "source", "entity_type"}
        }

    status = str(payload.get("status") or data.get("status") or "unknown")
    error_msg = payload.get("error_msg") or payload.get("error")
    if error_msg is not None:
        error_msg = str(error_msg)
    if error_msg and status == "unknown":
        status = "unreachable"
    return data, status, error_msg


def live_metric_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Map a normalized platform telemetry dict onto `HardwareLiveMetric` columns.

    Returns exactly the eight derived columns — never the attribution ones
    (`hardware_id`, `collected_at`, `status`, `source`, `raw`, `error_msg`, and
    the agent-only `agent_id`/`agent_sample_id`), which belong to the caller.
    Absent sources yield `None`, so the result is always safe to splat into a
    `HardwareLiveMetric(...)` constructor or a `bulk_insert_mappings` row.
    """
    return {
        "cpu_pct": _as_float(_first_present(data, "cpu_pct", "cpu")),
        "mem_pct": _derive_mem_pct(data),
        "mem_used_mb": (
            _as_float(data.get("mem_used_mb"))
            if data.get("mem_used_mb") is not None
            else _bytes_to_mb(data.get("mem_used"))
        ),
        "mem_total_mb": (
            _as_float(data.get("mem_total_mb"))
            if data.get("mem_total_mb") is not None
            else _bytes_to_mb(data.get("mem_total"))
        ),
        "disk_pct": _derive_disk_pct(data),
        "temp_c": _as_float(_first_present(data, "temp_c", "cpu_temp")),
        "power_w": _as_float(_first_present(data, "power_w", "system_power_w")),
        "uptime_s": _as_int(_first_present(data, "uptime_s", "uptime")),
    }


def _root_filesystem(filesystems: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The `/` entry of a `telemetry.host` payload's `filesystems` list.

    Root-disk *bytes* are not in the agent summary — `HostSummary` carries only
    `root_disk_pct` — so `rootfs_used`/`disk_used_gb` can only come from here.
    """
    for entry in filesystems or ():
        if isinstance(entry, Mapping) and entry.get("mountpoint") == _ROOT_MOUNTPOINT:
            return entry
    return None


def agent_summary_to_platform(
    summary: Mapping[str, Any],
    filesystems: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Translate an agent `telemetry.host` summary into the platform vocabulary.

    Every key is **omitted rather than set to `None`** when its source is
    absent, so :func:`_derive_mem_pct` / :func:`_derive_disk_pct` fall back the
    way they do for poller payloads.

    Deliberately emits no `power_w`/`system_power_w`: the Linux host collector
    has no power probe, so `HardwareLiveMetric.power_w` stays NULL and the map
    node's wattage badge correctly renders nothing. Do not fake it.
    """
    platform: dict[str, Any] = {}

    def put(key: str, value: Any) -> None:
        if value is not None:
            platform[key] = value

    put("cpu_pct", _as_float(summary.get("cpu_pct")))
    put("mem_pct", _as_float(summary.get("mem_pct")))

    # Bytes stay as reported; the MiB/GiB views are derived for the consumers
    # that render them (`TelemetrySidebar` falls back to bytes, `CustomNode`
    # does not and needs `mem_used_gb`/`mem_total_gb` outright).
    if summary.get("mem_used_bytes") is not None:
        put("mem_used", summary["mem_used_bytes"])
        put("mem_used_mb", _bytes_to_mb(summary["mem_used_bytes"]))
        put("mem_used_gb", _bytes_to_gb(summary["mem_used_bytes"]))
    if summary.get("mem_total_bytes") is not None:
        put("mem_total", summary["mem_total_bytes"])
        put("mem_total_mb", _bytes_to_mb(summary["mem_total_bytes"]))
        put("mem_total_gb", _bytes_to_gb(summary["mem_total_bytes"]))

    put("disk_pct", _as_float(summary.get("root_disk_pct")))
    root = _root_filesystem(filesystems)
    if root is not None:
        if root.get("used_bytes") is not None:
            put("rootfs_used", root["used_bytes"])
            put("disk_used_gb", _bytes_to_gb(root["used_bytes"]))
        if root.get("total_bytes") is not None:
            put("rootfs_total", root["total_bytes"])
            put("disk_total_gb", _bytes_to_gb(root["total_bytes"]))

    # `temp_c` is the canonical name; `cpu_temp` is the alias `CustomNode.jsx`
    # reads, so both are emitted rather than making the UI guess.
    max_temp = _as_float(summary.get("max_temp_c"))
    put("temp_c", max_temp)
    put("cpu_temp", max_temp)

    # The collector genuinely emits a float uptime; round rather than truncate
    # so the value matches what the BigInteger column would have stored.
    uptime = _as_float(summary.get("uptime_s"))
    put("uptime_s", None if uptime is None else round(uptime))

    for key in _AGENT_PASSTHROUGH_KEYS:
        if summary.get(key) is not None:
            platform[key] = summary[key]

    return platform
