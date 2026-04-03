"""
Batch import service: converts ScanResult rows into Hardware rows.

Deduplicates by MAC address first, then IP address.
All upserts execute in a single SAVEPOINT (begin_nested) for atomicity.
Computes subnet-grouped layout for newly created nodes and persists it server-side.
Idempotent: re-importing the same scan produces updated rows, not duplicates.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Hardware, ScanResult
from app.schemas.discovery import (
    BatchImportConflict,
    BatchImportCreated,
    BatchImportRequest,
    BatchImportResponse,
    ImportAsNetworkRequest,
    ImportAsNetworkResponse,
)
from app.services import device_role_service
from app.services.inference_service import annotate_result
from app.services.layout_service import compute_subnet_layout

_logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sanitise_overrides(overrides: dict, valid_slugs: set[str] | None = None) -> dict:
    allowed = {"name", "role", "vendor", "vendor_icon_slug", "notes"}
    clean = {k: v for k, v in overrides.items() if k in allowed}
    if "role" in clean and valid_slugs is not None and clean["role"] not in valid_slugs:
        del clean["role"]
    return clean


def _resolve_role_for_result(
    result: Any,  # ScanResult or duck-typed object
    hint_map: dict[str, str],
    hostname_pairs: list[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Return (auto_role, suggestion) for a scan result.

    auto_role: slug to assign immediately (confidence threshold met)
    suggestion: slug to store as role_suggestion (threshold not met but matched)
    """
    device_type = getattr(result, "device_type", None)
    confidence = getattr(result, "device_confidence", None) or 0
    hostname = (getattr(result, "hostname", None) or "").lower()

    # 1. device_type hint match — threshold 70
    if device_type and device_type in hint_map:
        slug = hint_map[device_type]
        if confidence >= 70:
            return slug, None
        else:
            return None, slug

    # 2. hostname pattern match — threshold 65
    for pattern, slug in hostname_pairs:
        if pattern in hostname:
            if confidence >= 65:
                return slug, None
            else:
                return None, slug

    return None, None


def batch_import(
    db: Session,
    job_id: int,
    request: BatchImportRequest,
    actor: str = "api",
) -> BatchImportResponse:
    response = BatchImportResponse()
    _hint_map = device_role_service.hint_map(db)
    _hostname_pairs = device_role_service.hostname_map(db)
    _valid_slugs = device_role_service.valid_slugs(db)

    for item in request.items:
        # Each item gets its own SAVEPOINT so a per-item DB error is isolated —
        # it does not roll back successfully processed items.
        sp = db.begin_nested()
        try:
            scan_result = db.get(ScanResult, item.scan_result_id)
            if not scan_result or scan_result.scan_job_id != job_id:
                sp.rollback()
                response.skipped.append(item.scan_result_id)
                continue

            ip = scan_result.ip_address
            mac = scan_result.mac_address

            # Lock candidate rows to prevent concurrent duplicate creation
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

            # Detect cross-match conflict: MAC resolves to different row than IP
            if hw_by_mac and hw_by_ip and hw_by_mac.id != hw_by_ip.id:
                sp.rollback()
                response.conflicts.append(
                    BatchImportConflict(
                        scan_result_id=item.scan_result_id,
                        ip=ip,
                        mac=mac,
                        reason=f"mac_matches_id_{hw_by_mac.id}_ip_matches_id_{hw_by_ip.id}",
                    )
                )
                continue

            auto_role, suggestion = _resolve_role_for_result(
                scan_result, _hint_map, _hostname_pairs
            )
            if suggestion:
                scan_result.role_suggestion = suggestion

            existing = hw_by_mac or hw_by_ip
            overrides = _sanitise_overrides(item.overrides, _valid_slugs)

            if existing:
                existing.last_seen = _now_iso()
                if mac and existing.mac_address != mac:
                    existing.mac_address = mac
                if scan_result.hostname and existing.hostname != scan_result.hostname:
                    existing.hostname = scan_result.hostname
                # Role override applies regardless of source — user made an explicit choice.
                if "role" in overrides:
                    existing.role = overrides.pop("role")
                # Other fields (name, vendor, notes) only overwrite discovery-sourced records
                # to preserve manual edits on non-discovery hardware.
                if getattr(existing, "source", None) == "discovery":
                    for k, v in overrides.items():
                        setattr(existing, k, v)
                existing.source_scan_result_id = scan_result.id
                db.flush()
                scan_result.merge_status = "accepted"
                scan_result.reviewed_at = _now_iso()
                scan_result.reviewed_by = actor
                if not scan_result.matched_entity_id:
                    scan_result.matched_entity_type = "hardware"
                    scan_result.matched_entity_id = existing.id
                db.flush()
                sp.commit()
                response.updated.append(
                    BatchImportCreated(id=existing.id, ip=ip, scan_result_id=scan_result.id)
                )
            else:
                ann = annotate_result(scan_result)
                name = (
                    overrides.pop("name", None)
                    or scan_result.hostname
                    or ip
                    or f"device-{scan_result.id}"
                )
                final_role = overrides.pop("role", None) or auto_role or ann.role or "misc"
                if final_role not in _valid_slugs:
                    final_role = "misc"
                hw = Hardware(
                    name=name,
                    ip_address=ip,
                    mac_address=mac,
                    hostname=scan_result.hostname,
                    role=final_role,
                    vendor=overrides.pop("vendor", None) or ann.vendor,
                    vendor_icon_slug=overrides.pop("vendor_icon_slug", None)
                    or ann.vendor_icon_slug,
                    source="discovery",
                    discovered_at=_now_iso(),
                    last_seen=_now_iso(),
                    source_scan_result_id=scan_result.id,
                )
                for k, v in overrides.items():
                    setattr(hw, k, v)
                db.add(hw)
                db.flush()
                scan_result.merge_status = "accepted"
                scan_result.reviewed_at = _now_iso()
                scan_result.reviewed_by = actor
                if not scan_result.matched_entity_id:
                    scan_result.matched_entity_type = "hardware"
                    scan_result.matched_entity_id = hw.id
                db.flush()
                sp.commit()
                response.created.append(
                    BatchImportCreated(id=hw.id, ip=ip, scan_result_id=scan_result.id)
                )
        except Exception as exc:
            sp.rollback()
            _logger.warning(
                "batch_import: item scan_result_id=%s failed, skipping — %s",
                item.scan_result_id,
                exc,
            )
            response.skipped.append(item.scan_result_id)

    # Compute layout for newly created nodes only (updated nodes keep their positions)
    if response.created:
        hw_list = []
        for c in response.created:
            hw_obj = db.get(Hardware, c.id)
            if hw_obj:
                hw_list.append({"id": c.id, "ip_address": c.ip, "role": hw_obj.role})
        positions = compute_subnet_layout(hw_list)
        for created_item in response.created:
            created_item.position = positions.get(created_item.id)
        _persist_layout(db, positions)

    db.commit()
    return response


def _persist_layout(db: Session, positions: dict[int, dict]) -> None:
    """Save positions to the graph layout table (server-side, non-fatal on failure)."""
    try:
        from app.services.graph_service import save_layout

        str_positions = {str(k): v for k, v in positions.items()}
        save_layout(db, "default", str_positions)
    except Exception as exc:
        _logger.warning("Layout persistence failed (non-fatal): %s", exc)


def _ensure_placeholder_gateways(
    db: Session,
    nodes: list[dict],
    map_id: int,
) -> list[dict]:
    """
    For each /24 subnet that has only endpoint nodes (no firewall/router/switch),
    create a placeholder Hardware row and assign it to the map.
    Returns list of {id, ip_address, role} dicts for the new placeholders.
    """
    from app.db.models import TopologyNode
    from app.services.topology_inference_service import ROLE_RANK, _subnet_key

    subnets: dict[str, list[dict]] = {}
    for node in nodes:
        key = _subnet_key(node.get("ip_address"))
        subnets.setdefault(key, []).append(node)

    created: list[dict] = []
    for subnet_key_val, subnet_nodes in subnets.items():
        has_chain = any(ROLE_RANK.get(n.get("role") or "misc", 5) <= 3 for n in subnet_nodes)
        if has_chain or subnet_key_val == "__no_ip__":
            continue

        existing_placeholder = db.execute(
            select(Hardware).where(
                Hardware.is_placeholder.is_(True),
                Hardware.name == f"Unknown Gateway ({subnet_key_val}.0/24)",
            )
        ).scalar_one_or_none()
        if existing_placeholder:
            existing_assignment = db.execute(
                select(TopologyNode).where(
                    TopologyNode.topology_id == map_id,
                    TopologyNode.entity_type == "hardware",
                    TopologyNode.entity_id == existing_placeholder.id,
                )
            ).scalar_one_or_none()
            if not existing_assignment:
                db.add(
                    TopologyNode(
                        topology_id=map_id,
                        entity_type="hardware",
                        entity_id=existing_placeholder.id,
                    )
                )
                db.flush()
            created.append(
                {
                    "id": existing_placeholder.id,
                    "ip_address": None,
                    "role": "router",
                    "subnet": subnet_key_val,
                }
            )
            continue

        placeholder = Hardware(
            name=f"Unknown Gateway ({subnet_key_val}.0/24)",
            ip_address=None,
            role="router",
            source="discovery",
            is_placeholder=True,
            discovered_at=_now_iso(),
            last_seen=_now_iso(),
        )
        db.add(placeholder)
        db.flush()

        db.add(TopologyNode(topology_id=map_id, entity_type="hardware", entity_id=placeholder.id))
        db.flush()

        created.append(
            {
                "id": placeholder.id,
                "ip_address": None,
                "role": "router",
                "subnet": subnet_key_val,
            }
        )

    return created


def import_as_network(
    db: Session,
    job_id: int,
    request: ImportAsNetworkRequest,
    actor: str = "api",
) -> ImportAsNetworkResponse:
    from app.db.models import GraphLayout, Hardware, Topology, TopologyNode
    from app.schemas.discovery import (
        BatchImportRequest,
        ImportAsNetworkPlaceholder,
        ImportAsNetworkResponse,
    )
    from app.services.layout_service import compute_subnet_layout
    from app.services.topology_inference_service import apply_inferred_topology

    # Resolve map_id: use provided value or auto-select main map (lowest id)
    map_id = request.map_id
    if map_id is None:
        main_map = db.execute(select(Topology).order_by(Topology.id.asc())).scalars().first()
        if main_map is None:
            main_map = Topology(name="Main")
            db.add(main_map)
            db.flush()
        map_id = main_map.id

    # Step 1: Create hardware nodes using existing dedup logic
    batch_req = BatchImportRequest(items=request.items)
    batch_resp = batch_import(db, job_id, batch_req, actor)

    # Build role overrides from items that explicitly set a role
    _scan_result_to_role: dict[int, str] = {
        item.scan_result_id: item.overrides["role"]
        for item in request.items
        if item.overrides.get("role")
    }
    hw_role_overrides: dict[int, str] = {}
    for c in batch_resp.created + batch_resp.updated:
        if c.scan_result_id and c.scan_result_id in _scan_result_to_role:
            hw_role_overrides[c.id] = _scan_result_to_role[c.scan_result_id]

    # Step 2: Assign all created/updated nodes to the map
    all_hw_ids = [c.id for c in batch_resp.created] + [u.id for u in batch_resp.updated]
    for hw_id in all_hw_ids:
        already = db.execute(
            select(TopologyNode).where(
                TopologyNode.topology_id == map_id,
                TopologyNode.entity_type == "hardware",
                TopologyNode.entity_id == hw_id,
            )
        ).scalar_one_or_none()
        if not already:
            db.add(
                TopologyNode(
                    topology_id=map_id,
                    entity_type="hardware",
                    entity_id=hw_id,
                )
            )
    db.flush()

    # Step 3: Build node list for inference
    hw_rows = db.execute(select(Hardware).where(Hardware.id.in_(all_hw_ids))).scalars().all()
    nodes = [{"id": hw.id, "ip_address": hw.ip_address, "role": hw.role} for hw in hw_rows]

    # Step 3b: Include all Hardware records on the same /24 subnets so that
    # pre-existing routers/switches not in this scan batch can anchor topology.
    from app.services.topology_inference_service import _subnet_key

    batch_id_set = set(all_hw_ids)
    subnet_prefixes = {
        _subnet_key(hw.ip_address)
        for hw in hw_rows
        if hw.ip_address and _subnet_key(hw.ip_address) != "__no_ip__"
    }
    if subnet_prefixes:
        all_hw_rows = (
            db.execute(select(Hardware).where(Hardware.ip_address.isnot(None))).scalars().all()
        )
        for hw in all_hw_rows:
            if hw.id in batch_id_set:
                continue
            if _subnet_key(hw.ip_address) in subnet_prefixes:
                nodes.append({"id": hw.id, "ip_address": hw.ip_address, "role": hw.role})

    # Step 4: Create placeholder gateways for subnets with no chain nodes
    stub_dicts = _ensure_placeholder_gateways(db, nodes, map_id)
    nodes.extend(stub_dicts)

    # Step 5: Infer topology and persist edges
    all_node_ids = all_hw_ids + [s["id"] for s in stub_dicts]
    edges_created = apply_inferred_topology(
        db,
        all_node_ids,
        map_id,
        actor=actor,
        role_overrides=hw_role_overrides or None,
        rank_map=device_role_service.rank_map(db),
    )

    # Step 7: Compute layout and save
    layout_input = [
        {"id": n["id"], "ip_address": n.get("ip_address"), "role": n.get("role")} for n in nodes
    ]
    positions = compute_subnet_layout(layout_input)
    layout_row = db.execute(
        select(GraphLayout).where(GraphLayout.topology_id == map_id)
    ).scalar_one_or_none()
    if layout_row:
        merged = dict(layout_row.layout_data) if layout_row.layout_data else {}
        merged.update({str(k): v for k, v in positions.items()})
        layout_row.layout_data = merged
    else:
        db.add(
            GraphLayout(
                name=f"map-{map_id}",
                topology_id=map_id,
                layout_data={str(k): v for k, v in positions.items()},
            )
        )
    db.flush()
    db.commit()

    stubs = [
        ImportAsNetworkPlaceholder(id=s["id"], subnet=s.get("subnet", "unknown"))
        for s in stub_dicts
    ]
    return ImportAsNetworkResponse(
        created=batch_resp.created,
        updated=batch_resp.updated,
        placeholders=stubs,
        edges_created=edges_created,
        conflicts=batch_resp.conflicts,
    )
