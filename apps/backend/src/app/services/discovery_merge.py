"""Scan result merging — accept, reject, auto-merge, and bulk operations."""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.log_sanitize import safe_log_fragment
from app.core.time import utcnow_iso
from app.db.models import (
    AppSettings,
    Hardware,
    Integration,
    IntegrationMonitor,
    KbOui,
    ScanResult,
    Service,
    Topology,
    TopologyNode,
)
from app.schemas.discovery import ScanResultOut
from app.services.discovery_fingerprint import _kb_oui_lookup
from app.services.discovery_network import PORT_SERVICE_MAP, _norm_mac
from app.services.discovery_proxmox_merge import _merge_proxmox_result
from app.services.log_service import write_log

logger = logging.getLogger(__name__)


def _assign_to_default_map(db: Session, entity_type: str, entity_id: int) -> None:
    """Add entity to the default topology map if not already present. No-commit — caller commits."""
    from sqlalchemy import select

    topo = db.execute(select(Topology).where(Topology.is_default == True)).scalar_one_or_none()  # noqa: E712
    if topo is None:
        topo = db.execute(
            select(Topology).order_by(Topology.sort_order, Topology.id)
        ).scalar_one_or_none()
    if topo is None:
        return
    exists = db.execute(
        select(TopologyNode).where(
            TopologyNode.topology_id == topo.id,
            TopologyNode.entity_type == entity_type,
            TopologyNode.entity_id == entity_id,
        )
    ).scalar_one_or_none()
    if not exists:
        db.add(TopologyNode(topology_id=topo.id, entity_type=entity_type, entity_id=entity_id))
        db.flush()


def _maybe_auto_create_native_monitor(db: Session, hardware: Hardware) -> None:
    """If auto_monitor_on_discovery is enabled, create a native monitor for new hardware.

    Non-blocking: exceptions are caught so they never roll back the caller's transaction.
    Call this after db.flush() so hardware.id is populated, but before db.commit().
    """
    try:
        settings = db.query(AppSettings).first()
        if not settings or not settings.auto_monitor_on_discovery:
            return
        native = db.query(Integration).filter(Integration.type == "native").first()
        if not native:
            return
        # Idempotent — skip if a monitor already exists for this hardware
        existing = (
            db.query(IntegrationMonitor)
            .filter(
                IntegrationMonitor.integration_id == native.id,
                IntegrationMonitor.linked_hardware_id == hardware.id,
            )
            .first()
        )
        if existing:
            return
        from app.integrations.native_probe import derive_probe_config

        probe_type, probe_target, probe_port = derive_probe_config(hardware=hardware)
        if not probe_target:
            return  # nothing to probe
        monitor = IntegrationMonitor(
            integration_id=native.id,
            external_id=f"native-hw-{hardware.id}",
            name=hardware.name,
            linked_hardware_id=hardware.id,
            probe_type=probe_type,
            probe_target=probe_target,
            probe_port=probe_port,
            probe_interval_s=60,
            status="pending",
        )
        db.add(monitor)
        logger.info(
            "Auto-created native monitor for hardware %d (%s) probe=%s target=%s",
            hardware.id,
            hardware.name,
            probe_type,
            probe_target,
        )
    except Exception:
        logger.exception(
            "Failed to auto-create native monitor for hardware %d — continuing", hardware.id
        )


async def _emit_result_processed_event(db: Session, result_id: int, status: str) -> None:
    """Emit WebSocket and NATS event for result processing (accept/reject)."""
    from app.services.discovery_service import _emit_ws_event

    try:
        # Get the result from database
        result = db.query(ScanResult).filter(ScanResult.id == result_id).first()
        if not result:
            logger.warning("Cannot emit result_processed event: result %d not found", result_id)
            return

        # Prepare payload with result data and status
        payload = {
            "job_id": result.scan_job_id,
            "result": ScanResultOut.model_validate(result).model_dump(),
            "status": status,
        }

        # Emit the event
        await _emit_ws_event("result_processed", payload)

    except Exception as exc:
        logger.warning("Failed to emit result_processed event for result %d: %s", result_id, exc)


def _build_ports_list(open_ports_json: str | None) -> list:
    """Build the ports suggestion list returned to the frontend after accepting a new host."""
    if not open_ports_json:
        return []
    try:
        ports = json.loads(open_ports_json)
    except Exception:
        return []
    result = []
    for p in ports:
        port_num = int(p.get("port", 0))
        protocol = p.get("protocol", "tcp")
        mapping = PORT_SERVICE_MAP.get(port_num)
        if mapping:
            result.append(
                {
                    "port": port_num,
                    "protocol": protocol,
                    "suggested_name": mapping["name"],
                    "suggested_category": mapping["type"],
                }
            )
        else:
            result.append(
                {
                    "port": port_num,
                    "protocol": protocol,
                    "suggested_name": p.get("name") or "Unknown",
                    "suggested_category": "misc",
                }
            )
    return result


def _make_service_slug(db: Session, name: str, hardware_id: int) -> str:
    """Generate a unique slug for a discovery-created service.

    Derives a base slug from the service name, then appends the hardware_id
    to avoid collisions when the same port name appears on multiple hosts.
    Falls back to appending an incrementing counter if the slug still collides.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    candidate = f"{base}-hw{hardware_id}"
    # Guard against UNIQUE constraint violation
    from sqlalchemy import select as _select

    from app.db.models import Service as _Service

    counter = 1
    while db.execute(_select(_Service).where(_Service.slug == candidate)).scalar_one_or_none():
        candidate = f"{base}-hw{hardware_id}-{counter}"
        counter += 1
    return candidate


def _auto_merge_result(db: Session, result: ScanResult, actor: str = "system") -> None:
    """
    Attempt to automatically merge a scan result into the system without manual intervention.
    Called when discovery_auto_merge is true, or via API bulk action.
    """
    if result.merge_status != "pending":
        return

    now = utcnow_iso()

    # Update existing match
    if result.state == "matched" and result.matched_entity_type == "hardware":
        hw = db.query(Hardware).filter(Hardware.id == result.matched_entity_id).first()
        if hw:
            # Update last_seen
            hw.last_seen = now
            hw.status = "online"
            # Supplement missing info
            if not hw.mac_address and result.mac_address:
                hw.mac_address = result.mac_address
            if not hw.os_version and result.os_family:
                hw.os_version = result.os_family
            db.commit()

            result.merge_status = "merged"
            db.commit()
            return

    # Create new entity
    if result.state == "new":
        # Create a new piece of hardware
        name = result.hostname or result.snmp_sys_name or f"Discovered Host - {result.ip_address}"
        # Determine hardware role based on OS or ports (heuristics)
        # For simplicity, default to server.
        hw = Hardware(
            name=name,
            role="server",
            ip_address=result.ip_address,
            mac_address=result.mac_address,
            vendor=result.os_vendor,
            status="online",
            source="discovery",
            discovered_at=now,
            last_seen=now,
            created_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
            updated_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
        )
        db.add(hw)
        db.flush()
        _assign_to_default_map(db, "hardware", hw.id)
        db.commit()
        db.refresh(hw)

        # Link services based on open ports
        if result.open_ports_json:
            try:
                ports = json.loads(result.open_ports_json)  # type: ignore[arg-type]
                for p in ports:
                    port_num = int(p["port"])
                    if port_num in PORT_SERVICE_MAP:
                        s_map = PORT_SERVICE_MAP[port_num]
                        svc_name = f"{s_map['name']} on {hw.name}"
                        svc = Service(
                            name=svc_name,
                            slug=_make_service_slug(db, svc_name, hw.id),
                            status="running",
                            hardware_id=hw.id,
                            ports_json=json.dumps(
                                [
                                    {
                                        "port": port_num,
                                        "protocol": p.get("protocol", "tcp"),
                                    }
                                ]
                            ),
                        )
                        db.add(svc)
                db.commit()
            except Exception as e:
                logger.debug("Discovery: auto-merge service creation failed: %s", e, exc_info=True)

        result.matched_entity_type = "hardware"
        result.matched_entity_id = hw.id
        result.merge_status = "merged"
        db.commit()

        write_log(
            db,
            action="result_auto_merged",
            entity_type="hardware",
            entity_id=hw.id,
            category="discovery",
            actor=actor,
            details=json.dumps(
                {"ip": result.ip_address, "source": "nmap", "scan_result_id": result.id}
            ),
        )


def maybe_learn_oui(scan_result: ScanResult, db: Session) -> None:
    """If the accepted device has a valid unicast MAC and a confirmed vendor,
    upsert its OUI prefix into the learned kb_oui table.

    Skips locally-administered MACs (bit 1 of first byte set) and prefixes
    already covered by the curated device_kb.json.
    """
    mac = scan_result.mac_address
    vendor = scan_result.os_vendor
    if not mac or not vendor:
        return

    # Skip locally-administered MACs — they have no OUI meaning
    try:
        first_byte = int(mac.split(":")[0], 16)
    except (ValueError, IndexError):
        return
    if first_byte & 0x02:
        return

    prefix = mac.upper().replace(":", "").replace("-", "")[:6]
    if len(prefix) != 6:
        return

    # Don't shadow entries already in the curated JSON
    if _kb_oui_lookup(mac):
        return

    existing = db.get(KbOui, prefix)
    if existing:
        existing.seen_count += 1
        existing.last_seen_at = datetime.now(UTC)
        # Don't overwrite a confirmed vendor — increment count only
    else:
        db.add(
            KbOui(
                prefix=prefix,
                vendor=vendor[:128],
                device_type=getattr(scan_result, "device_type", None),
                source="learned",
            )
        )
    db.commit()


def merge_scan_result(
    db: Session,
    result_id: int,
    action: str,
    entity_type: str | None = None,
    overrides: dict | None = None,
    actor: str = "api",
) -> dict:
    """Accept or reject a single scan result.

    Returns:
      reject              → {'rejected': True}
      accept + matched    → {'updated': True}
      accept + new        → {'entity_type': ..., 'entity_id': ..., 'ports': [...]}
    Raises HTTP 404 if not found.
    Raises HTTP 409 if already accepted/rejected or matched hardware row is gone.
    """
    if overrides is None:
        overrides = {}
    result = db.query(ScanResult).filter(ScanResult.id == result_id).first()
    if not result:
        raise HTTPException(status_code=404, detail="Scan result not found")

    if result.merge_status not in ("pending",):
        raise HTTPException(
            status_code=409, detail=f"Result already has merge_status='{result.merge_status}'"
        )

    now = utcnow_iso()

    # ── reject ──────────────────────────────────────────────────────────────
    if action == "reject":
        result.merge_status = "rejected"
        result.reviewed_by = actor
        result.reviewed_at = now
        db.commit()
        write_log(
            db,
            action="result_rejected",
            entity_type="scan_result",
            entity_id=result.id,
            category="discovery",
            actor=actor,
            details=json.dumps({"ip": result.ip_address, "hostname": result.hostname}),
        )

        # Emit WebSocket event for real-time badge update
        try:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_emit_result_processed_event(db, result.id, "reject"))
            else:
                asyncio.run(_emit_result_processed_event(db, result.id, "reject"))
        except Exception as e:
            logger.debug("Discovery: WebSocket emit reject failed: %s", e, exc_info=True)

        return {"rejected": True}

    # ── accept ───────────────────────────────────────────────────────────────
    if action == "accept":
        if result.source_type == "proxmox":
            return _merge_proxmox_result(db, result, overrides, actor, now)

        # CB-CASCADE-005: wrap accept branch in a savepoint for atomicity
        sp = db.begin_nested()
        try:
            # Normalize MAC before writing (CB-PATTERN-001)
            norm_mac = _norm_mac(result.mac_address)

            # conflict / matched: update existing entity with overrides
            if result.state in ("matched", "conflict") and result.matched_entity_type == "hardware":
                hw = db.query(Hardware).filter(Hardware.id == result.matched_entity_id).first()
                if not hw:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Scan result {result.id} points to hardware id "
                            f"{result.matched_entity_id}, which no longer exists. "
                            "The device may have been deleted; re-run discovery or clear the match."
                        ),
                    )
                hw.last_seen = now
                hw.status = "online"
                # CB-REL-001: link scan result to hardware
                hw.source_scan_result_id = result.id
                if not hw.mac_address and norm_mac:
                    hw.mac_address = norm_mac
                if not hw.os_version and result.os_family:
                    hw.os_version = result.os_family
                for k, v in overrides.items():
                    if hasattr(hw, k):
                        setattr(hw, k, v)
                db.flush()

                result.merge_status = "accepted"
                result.reviewed_by = actor
                result.reviewed_at = now
                db.flush()
                sp.commit()
                db.commit()
                maybe_learn_oui(result, db)
                write_log(
                    db,
                    action="result_accepted",
                    entity_type=result.matched_entity_type or "hardware",
                    entity_id=result.matched_entity_id,
                    category="discovery",
                    actor=actor,
                    details=json.dumps(
                        {
                            "scan_result_id": result.id,
                            "ip": result.ip_address,
                            "hostname": result.hostname,
                            "overrides": overrides,
                        }
                    ),
                )

                # Emit WebSocket event for real-time badge update
                try:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(_emit_result_processed_event(db, result.id, "accept"))
                    else:
                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
                except Exception as e:
                    logger.debug(
                        "Discovery: WebSocket emit accept (updated) failed: %s", e, exc_info=True
                    )

                return {"updated": True}

            # new host: create hardware entity
            if result.state == "new":
                name = (
                    overrides.get("name")
                    or result.hostname
                    or result.snmp_sys_name
                    or f"Discovered Host - {result.ip_address}"
                )
                role = overrides.get("role") or "server"

                hw = Hardware(
                    name=name,
                    role=role,
                    ip_address=result.ip_address,
                    mac_address=norm_mac,
                    vendor=result.os_vendor,
                    status="online",
                    source="discovery",
                    discovered_at=now,
                    last_seen=now,
                    source_scan_result_id=result.id,  # CB-REL-001
                    created_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
                    updated_at=datetime.fromisoformat(now) if "T" in now else datetime.now(),
                )
                for k, v in overrides.items():
                    if hasattr(hw, k):
                        setattr(hw, k, v)
                db.add(hw)
                db.flush()
                _maybe_auto_create_native_monitor(db, hw)
                _assign_to_default_map(db, "hardware", hw.id)

                result.matched_entity_type = "hardware"
                result.matched_entity_id = hw.id
                result.merge_status = "accepted"
                result.reviewed_by = actor
                result.reviewed_at = now
                db.flush()
                sp.commit()
                db.commit()
                db.refresh(hw)
                maybe_learn_oui(result, db)

                write_log(
                    db,
                    action="result_accepted",
                    entity_type="hardware",
                    entity_id=hw.id,
                    category="discovery",
                    actor=actor,
                    details=json.dumps(
                        {
                            "scan_result_id": result.id,
                            "ip": result.ip_address,
                            "hostname": result.hostname,
                            "overrides": overrides,
                        }
                    ),
                )

                # Emit WebSocket event for real-time badge update
                try:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(_emit_result_processed_event(db, result.id, "accept"))
                    else:
                        asyncio.run(_emit_result_processed_event(db, result.id, "accept"))
                except Exception as e:
                    logger.debug(
                        "Discovery: WebSocket emit accept (new host) failed: %s", e, exc_info=True
                    )

                return {
                    "entity_type": "hardware",
                    "entity_id": hw.id,
                    "ports": _build_ports_list(result.open_ports_json),  # type: ignore[arg-type]
                }

            # If we reach here inside the savepoint without matching a branch, commit savepoint
            sp.commit()
        except Exception:
            if sp.is_active:
                sp.rollback()
            raise

    return {"skipped": True}


def bulk_merge_results(db: Session, result_ids: list[int], action: str, actor: str = "api") -> dict:
    """Bulk accept or reject scan results.
    For bulk accept, conflict rows are skipped (they always require per-field review).
    Returns {'accepted': N, 'rejected': N, 'skipped': N}.
    """
    accepted = 0
    rejected = 0
    skipped = 0
    for rid in result_ids:
        result = db.query(ScanResult).filter(ScanResult.id == rid).first()
        if not result:
            skipped += 1
            continue
        # Conflicts must be reviewed individually on accept
        if action == "accept" and result.state == "conflict":
            skipped += 1
            continue
        try:
            merge_scan_result(db, rid, action, actor=actor)
            if action == "accept":
                accepted += 1
            else:
                rejected += 1
        except Exception as e:
            logger.error(f"Bulk merge failed for result {rid}: {e}")
            skipped += 1
    return {"accepted": accepted, "rejected": rejected, "skipped": skipped}


def enhanced_bulk_merge(db: Session, payload: Any, actor: str = "api") -> dict:
    """Enhanced bulk merge: accept scan results + optionally create/link cluster,
    network, rack assignment, per-node overrides, and auto-create services.

    Returns summary dict with created entity counts and hardware IDs.
    """
    from app.db.models import (
        HardwareCluster,
        HardwareClusterMember,
        HardwareNetwork,
    )
    from app.db.models import (
        Network as NetworkModel,
    )
    from app.services.bulk_suggest import EXTENDED_PORT_SERVICE_MAP, _parse_ports

    merged = 0
    skipped = 0
    hardware_ids = []
    hw_role_overrides: dict[int, str] = {}
    created_clusters = 0
    created_networks = 0
    created_services = 0
    errors = []

    # Build per-result assignment lookup
    assignment_map = {}
    for a in payload.assignments or []:
        assignment_map[a.result_id] = a

    # ── Step A: Cluster ──────────────────────────────────────────────────────
    cluster_id = None
    if payload.cluster:
        existing_cluster = (
            db.query(HardwareCluster).filter(HardwareCluster.name == payload.cluster.name).first()
        )
        if existing_cluster:
            cluster_id = existing_cluster.id
        else:
            cluster = HardwareCluster(
                name=payload.cluster.name,
                description=payload.cluster.description,
                environment=payload.cluster.environment,
                location=payload.cluster.location,
            )
            db.add(cluster)
            db.flush()
            cluster_id = cluster.id
            created_clusters = 1

    # ── Step B: Network ──────────────────────────────────────────────────────
    network_id = None
    if payload.network:
        if payload.network.existing_id:
            network_id = payload.network.existing_id
        else:
            # Check for existing by CIDR
            if payload.network.cidr:
                existing_net = (
                    db.query(NetworkModel).filter(NetworkModel.cidr == payload.network.cidr).first()
                )
                if existing_net:
                    network_id = existing_net.id
            if not network_id:
                net = NetworkModel(
                    name=payload.network.name,
                    cidr=payload.network.cidr,
                    vlan_id=payload.network.vlan_id,
                    gateway=payload.network.gateway,
                    description=payload.network.description,
                )
                db.add(net)
                db.flush()
                network_id = net.id
                created_networks = 1

    # ── Step C: Merge each result ────────────────────────────────────────────
    # ── Batch pre-load all ScanResults in one query ──────────────────────────
    _all_results = db.query(ScanResult).filter(ScanResult.id.in_(payload.result_ids)).all()
    _results_by_id: dict[int, ScanResult] = {r.id: r for r in _all_results}

    for rid in payload.result_ids:
        result = _results_by_id.get(rid)
        if not result:
            skipped += 1
            continue
        if result.state == "conflict":
            skipped += 1
            continue
        if result.merge_status != "pending":
            skipped += 1
            continue

        # Build overrides from per-node assignment
        overrides = {}
        assignment = assignment_map.get(rid)
        if assignment:
            for field in (
                "vendor",
                "vendor_catalog_key",
                "model_catalog_key",
                "vendor_icon_slug",
                "role",
                "name",
                "rack_unit",
                "u_height",
            ):
                val = getattr(assignment, field, None)
                if val is not None:
                    overrides[field] = val

        # Apply rack_id from payload-level
        if payload.rack_id:
            overrides["rack_id"] = payload.rack_id

        try:
            merge_result = merge_scan_result(db, rid, "accept", overrides=overrides, actor=actor)
        except HTTPException as e:
            # detail is str | list | dict at runtime (validation errors); stubs often use only str.
            raw_detail: object = e.detail
            detail = raw_detail if isinstance(raw_detail, str) else json.dumps(raw_detail)
            logger.warning(
                "Enhanced bulk merge rejected for result %s: %s",
                rid,
                safe_log_fragment(detail, 400),
            )
            errors.append({"result_id": rid, "error": detail})
            skipped += 1
            continue
        except Exception as merge_exc:
            logger.error(
                "Enhanced bulk merge failed for result %s",
                rid,
                exc_info=True,
            )
            errors.append(
                {
                    "result_id": rid,
                    "error": safe_log_fragment(merge_exc, 500),
                }
            )
            skipped += 1
            continue

        merged += 1
        entity_id = merge_result.get("entity_id")
        if not entity_id and merge_result.get("updated"):
            # For matched results, get the hardware ID from the result
            entity_id = result.matched_entity_id

        if entity_id:
            # Defense in depth: bulk-merge links require a real hardware row (race / stale UI).
            if db.query(Hardware.id).filter(Hardware.id == entity_id).first() is None:
                logger.error(
                    "enhanced_bulk_merge: result %s entity_id=%s — no hardware row; skip links",
                    rid,
                    entity_id,
                )
                errors.append(
                    {
                        "result_id": rid,
                        "error": (
                            f"Hardware id {entity_id} missing after merge; "
                            "cluster/network/service links were skipped."
                        ),
                    }
                )
                continue

            hardware_ids.append(entity_id)
            if assignment and assignment.role:
                hw_role_overrides[entity_id] = assignment.role

            # Link to cluster
            if cluster_id:
                existing_member = (
                    db.query(HardwareClusterMember)
                    .filter(
                        HardwareClusterMember.cluster_id == cluster_id,
                        HardwareClusterMember.hardware_id == entity_id,
                    )
                    .first()
                )
                if not existing_member:
                    role = overrides.get("role") or (assignment.role if assignment else None)
                    member = HardwareClusterMember(
                        cluster_id=cluster_id,
                        hardware_id=entity_id,
                        role=role,
                    )
                    db.add(member)
                    db.flush()

            # Link to network
            if network_id:
                existing_link = (
                    db.query(HardwareNetwork)
                    .filter(
                        HardwareNetwork.network_id == network_id,
                        HardwareNetwork.hardware_id == entity_id,
                    )
                    .first()
                )
                if not existing_link:
                    hw_net = HardwareNetwork(
                        network_id=network_id,
                        hardware_id=entity_id,
                        ip_address=result.ip_address,
                    )
                    db.add(hw_net)
                    db.flush()

            # Auto-create services
            if payload.create_services:
                ports = _parse_ports(result.open_ports_json)
                for p in ports:
                    port_num = int(p.get("port", 0))
                    svc_info = EXTENDED_PORT_SERVICE_MAP.get(port_num)
                    if svc_info:
                        svc_name = svc_info["name"]
                        slug = _make_service_slug(db, svc_name, entity_id)
                        svc = Service(
                            name=svc_name,
                            slug=slug,
                            hardware_id=entity_id,
                            port=port_num,
                            protocol=p.get("protocol", "tcp"),
                            status="active",
                            source="discovery",
                        )
                        db.add(svc)
                        db.flush()
                        created_services += 1

    db.commit()

    # Infer topology for the accepted cohort
    if hardware_ids:
        from sqlalchemy import select as _sel

        from app.services.topology_inference_service import apply_inferred_topology

        topo = db.execute(
            _sel(Topology).where(Topology.is_default == True)  # noqa: E712
        ).scalar_one_or_none()
        if topo is None:
            topo = db.execute(
                _sel(Topology).order_by(Topology.sort_order, Topology.id)
            ).scalar_one_or_none()
        if topo is not None:
            apply_inferred_topology(
                db,
                list(hardware_ids),
                topo.id,
                actor=actor,
                role_overrides=hw_role_overrides or None,
            )
            db.commit()

    return {
        "merged": merged,
        "skipped": skipped,
        "created": {
            "clusters": created_clusters,
            "networks": created_networks,
            "services": created_services,
        },
        "hardware_ids": hardware_ids,
        "errors": errors,
    }
