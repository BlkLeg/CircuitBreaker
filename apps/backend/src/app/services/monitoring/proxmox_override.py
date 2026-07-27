"""Proxmox priority override: a fresh Proxmox opinion wins over a raw ICMP/TCP
check for monitors on Proxmox-linked targets (Hardware nodes, VMs/containers).

Runs once per batch in monitor_poll_worker.process_batch(), after collectors
have produced outcomes and before write_samples()/apply_result() run — so both
the stored avail sample and the state-machine transition see the corrected
result. Never raises: a defect here degrades a single item — or, if the
failure happens before per-item processing (e.g. a bad prefetch), the whole
batch — back to its raw, un-overridden outcome(s) rather than failing.

Only applies to raw ICMP/TCP checks: a hypervisor's opinion is evidence about
whether the node/VM/container is *running*, not about whether an
application-level service on top of it (HTTP, DNS, ...) is healthy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import ComputeUnit, Hardware
from app.services.monitoring.collectors import Sample
from app.services.monitoring.writer import SampleRow
from app.services.telemetry_service import _NON_LIVE_STATUSES

logger = logging.getLogger(__name__)

_FRESHNESS_WINDOW = timedelta(minutes=5)
_OVERRIDABLE_CHECK_TYPES = {"icmp", "tcp"}

Outcome = tuple[SampleRow, bool, str]


def apply_proxmox_overrides(
    db: Session, items: list[dict], outcomes: list[Outcome]
) -> list[Outcome]:
    try:
        targets_by_item = {item["item_id"]: item for item in items}
        cutoff = utcnow() - _FRESHNESS_WINDOW

        hardware_ids = {
            i["target_id"]
            for i in items
            if i["target_type"] == "hardware" and i["target_id"] is not None
        }
        compute_ids = {
            i["target_id"]
            for i in items
            if i["target_type"] == "compute_unit" and i["target_id"] is not None
        }
        hw_map = (
            {hw.id: hw for hw in db.query(Hardware).filter(Hardware.id.in_(hardware_ids)).all()}
            if hardware_ids
            else {}
        )
        cu_map = (
            {
                cu.id: cu
                for cu in db.query(ComputeUnit).filter(ComputeUnit.id.in_(compute_ids)).all()
            }
            if compute_ids
            else {}
        )

        result: list[Outcome] = []
        for outcome in outcomes:
            try:
                result.append(_apply_one(outcome, targets_by_item, hw_map, cu_map, cutoff))
            except Exception as exc:  # noqa: BLE001 — a defect here degrades to the raw outcome
                logger.warning("Proxmox override crashed, using raw outcome: %s", exc)
                result.append(outcome)
        return result
    except Exception as exc:  # noqa: BLE001 — never fail the batch over this feature
        logger.warning("Proxmox override batch prefetch crashed, using raw outcomes: %s", exc)
        return outcomes


def _apply_one(
    outcome: Outcome,
    targets_by_item: dict[int, dict],
    hw_map: dict[int, Hardware],
    cu_map: dict[int, ComputeUnit],
    cutoff: datetime,
) -> Outcome:
    row, up, msg = outcome
    item_id, target_type, target_id, samples, ts = row
    item = targets_by_item.get(item_id)
    if item is None:
        return outcome
    if item.get("check_type") not in _OVERRIDABLE_CHECK_TYPES:
        return outcome

    proxmox_up, label = _proxmox_opinion(item, hw_map, cu_map, cutoff)
    if proxmox_up is None or proxmox_up == up:
        return outcome

    new_samples = [
        Sample("avail", 1.0 if proxmox_up else 0.0) if s.metric == "avail" else s for s in samples
    ]
    state = "running" if proxmox_up else "stopped"
    new_msg = f"{msg} (overridden: Proxmox reports {label} {state})".strip()
    new_row = (item_id, target_type, target_id, new_samples, ts)
    logger.info(
        "Proxmox override: item %s (%s %s) raw=%s -> proxmox=%s",
        item_id,
        target_type,
        target_id,
        up,
        proxmox_up,
    )
    return new_row, proxmox_up, new_msg


def _proxmox_opinion(
    item: dict,
    hw_map: dict[int, Hardware],
    cu_map: dict[int, ComputeUnit],
    cutoff: datetime,
) -> tuple[bool | None, str]:
    target_type = item.get("target_type")
    target_id = item.get("target_id")
    if not isinstance(target_id, int):
        return None, ""

    if target_type == "hardware":
        hw = hw_map.get(target_id)
        if hw is None:
            return None, "node"
        is_fresh = (
            hw.proxmox_node_name
            and hw.telemetry_last_polled is not None
            and hw.telemetry_last_polled >= cutoff
        )
        # A fresh telemetry_last_polled alone is NOT sufficient evidence the node
        # is up: proxmox_discovery.py's _upsert_node() and the telemetry ingest
        # paths (telemetry_service.py, telemetry_ingest_worker.py) all also stamp
        # this column unconditionally, including for offline/unreachable nodes.
        # telemetry_status is the reliable liveness signal across all of those
        # writers — it lands in _NON_LIVE_STATUSES whenever the underlying poll
        # didn't confirm the node is actually live, so require it not be one of
        # those alongside freshness.
        is_live = is_fresh and hw.telemetry_status not in _NON_LIVE_STATUSES
        return (True, "node") if is_live else (None, "node")

    if target_type == "compute_unit":
        cu = cu_map.get(target_id)
        if cu is None:
            return None, ""
        is_fresh = (
            cu.proxmox_vmid is not None
            and cu.telemetry_last_polled is not None
            and cu.telemetry_last_polled >= cutoff
        )
        if not is_fresh:
            return None, ""
        label = "VM" if cu.kind == "vm" else "container"
        return cu.status == "active", label

    return None, ""
