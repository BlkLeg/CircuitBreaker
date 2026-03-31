from __future__ import annotations

from sqlalchemy.orm import Session

ROLE_RANK: dict[str, int] = {
    "firewall": 1,
    "router": 2,
    "switch": 3,
    "access_point": 4,
    "server": 5,
    "hypervisor": 5,
    "storage": 5,
    "compute": 5,
    "sbc": 5,
    "ups": 5,
    "pdu": 5,
    "misc": 5,
}


def _rank(role: str | None) -> int:
    return ROLE_RANK.get(role or "misc", 5)


def _subnet_key(ip: str | None) -> str:
    if not ip:
        return "__no_ip__"
    parts = ip.split(".")
    return ".".join(parts[:3]) if len(parts) == 4 else "__no_ip__"


def _gateway_score(ip: str | None) -> int:
    """Score an IP address by how likely it is to be a default gateway.

    .1 = 10 (classic RFC 1918 default gateway)
    .254 = 5 (Cisco/ISP alternate default)
    .2 = 2 (sometimes used when .1 is upstream)
    .126 = 1 (midpoint of /25)
    else = 0 (no signal)
    """
    if not ip:
        return 0
    last = ip.rsplit(".", 1)[-1]
    try:
        last_int = int(last)
    except ValueError:
        return 0
    if last_int == 1:
        return 10
    if last_int == 254:
        return 5
    if last_int == 2:
        return 2
    if last_int == 126:
        return 1
    return 0


def infer_connections(
    nodes: list[dict],
    role_overrides: dict[int, str] | None = None,
) -> list[tuple[int, int]]:
    """
    Given nodes as list[{id, ip_address, role}], return (source_id, target_id) pairs.
    Groups by /24 subnet. Nodes with no IP share a single no-ip group.

    role_overrides: {node_id: role} — takes absolute precedence over node["role"].
    When IPAM signals exist (score > 0) and no chain roles are present, scored nodes
    form an inferred chain (highest score first); score-0 nodes are endpoints.
    """
    overrides = role_overrides or {}

    def _effective_role(node: dict) -> str:
        return overrides.get(node["id"]) or node.get("role") or "misc"

    subnets: dict[str, list[dict]] = {}
    for node in nodes:
        ip = node.get("ip_address")
        if ip is None:
            key = node.get("subnet") or "__no_ip__"
        else:
            key = _subnet_key(ip)
        subnets.setdefault(key, []).append(node)

    edges: list[tuple[int, int]] = []

    for subnet_nodes in subnets.values():
        sorted_nodes = sorted(
            subnet_nodes,
            key=lambda n: (_rank(_effective_role(n)), -_gateway_score(n.get("ip_address"))),
        )
        chain = [n for n in sorted_nodes if _rank(_effective_role(n)) <= 3]
        endpoints = [n for n in sorted_nodes if _rank(_effective_role(n)) > 3]

        if not chain and subnet_nodes:
            # No explicit chain roles — use IPAM scoring to build a hierarchy.
            # Nodes with score > 0 form an inferred chain (highest score = most upstream).
            # Score-0 nodes are endpoints that connect to the last inferred-chain node.
            inferred_chain = [n for n in sorted_nodes if _gateway_score(n.get("ip_address")) > 0]
            inferred_endpoints = [
                n for n in sorted_nodes if _gateway_score(n.get("ip_address")) == 0
            ]
            if inferred_chain:
                for i in range(1, len(inferred_chain)):
                    edges.append((inferred_chain[i - 1]["id"], inferred_chain[i]["id"]))
                anchor = inferred_chain[-1]
                for ep in inferred_endpoints:
                    edges.append((anchor["id"], ep["id"]))
            else:
                # No IPAM signal — star from the highest-ranked device (unchanged fallback).
                hub = sorted_nodes[0]
                for ep in sorted_nodes[1:]:
                    edges.append((hub["id"], ep["id"]))
            continue

        # Connect chain nodes: each node connects to the nearest ancestor with lower rank.
        # Same-rank fallback: connect to the preceding chain node (sorted highest-score-first
        # by gateway score, so this preserves the .1 → .2 upstream ordering).
        for i in range(1, len(chain)):
            cur_rank = _rank(_effective_role(chain[i]))
            parent = next(
                (
                    chain[j]
                    for j in range(i - 1, -1, -1)
                    if _rank(_effective_role(chain[j])) < cur_rank
                ),
                chain[i - 1],
            )
            edges.append((parent["id"], chain[i]["id"]))

        # Connect endpoints to switch(es); fall back to last chain node.
        if chain and endpoints:
            switches = [n for n in chain if _effective_role(n) == "switch"]
            anchors = switches if switches else [chain[-1]]
            for i, ep in enumerate(endpoints):
                anchor = anchors[i % len(anchors)]
                edges.append((anchor["id"], ep["id"]))

    return edges


def apply_inferred_topology(
    db: Session,
    hw_ids: list[int],
    map_id: int,
    actor: str = "system",
    replace_existing_inferred: bool = True,
    role_overrides: dict[int, str] | None = None,
    connection_type: str = "ethernet",
) -> int:
    """
    Run topology inference over hw_ids (expanding to subnet peers on the same map),
    optionally delete prior discovery_inferred edges in the cohort, and persist
    new HardwareConnection rows. Returns the count of edges created.

    role_overrides: {hw_id: role} — written to Hardware.role in the DB AND applied
    at inference time. User-assigned roles are guaranteed to be the chain root.
    """
    from sqlalchemy import select

    from app.db.models import Hardware, HardwareConnection, TopologyNode

    if not hw_ids:
        return 0

    # Load the batch nodes
    hw_rows = db.execute(select(Hardware).where(Hardware.id.in_(hw_ids))).scalars().all()

    # Enforce role overrides at the DB level for guaranteed consistency
    if role_overrides:
        for hw in hw_rows:
            if hw.id in role_overrides and role_overrides[hw.id]:
                hw.role = role_overrides[hw.id]
        db.flush()

    nodes = [{"id": h.id, "ip_address": h.ip_address, "role": h.role} for h in hw_rows]

    # Expand to subnet peers already on this map
    batch_id_set = set(hw_ids)
    subnet_prefixes = {
        _subnet_key(hw.ip_address)
        for hw in hw_rows
        if hw.ip_address and _subnet_key(hw.ip_address) != "__no_ip__"
    }
    if subnet_prefixes:
        all_hw = db.execute(select(Hardware).where(Hardware.ip_address.isnot(None))).scalars().all()
        for hw in all_hw:
            if hw.id not in batch_id_set and _subnet_key(hw.ip_address) in subnet_prefixes:
                on_map = db.execute(
                    select(TopologyNode).where(
                        TopologyNode.topology_id == map_id,
                        TopologyNode.entity_type == "hardware",
                        TopologyNode.entity_id == hw.id,
                    )
                ).scalar_one_or_none()
                if on_map:
                    nodes.append({"id": hw.id, "ip_address": hw.ip_address, "role": hw.role})

    # Delete prior inferred edges in the cohort
    if replace_existing_inferred:
        stale = (
            db.execute(
                select(HardwareConnection).where(
                    HardwareConnection.source_hardware_id.in_(batch_id_set),
                    HardwareConnection.target_hardware_id.in_(batch_id_set),
                    HardwareConnection.source == "discovery_inferred",
                )
            )
            .scalars()
            .all()
        )
        for edge in stale:
            db.delete(edge)
        db.flush()

    # Infer and persist new edges
    edge_pairs = infer_connections(nodes, role_overrides=role_overrides)
    created = 0
    for src_id, tgt_id in edge_pairs:
        exists = (
            db.execute(
                select(HardwareConnection).where(
                    HardwareConnection.source_hardware_id == src_id,
                    HardwareConnection.target_hardware_id == tgt_id,
                )
            )
            .scalars()
            .first()
        )
        if not exists:
            db.add(
                HardwareConnection(
                    source_hardware_id=src_id,
                    target_hardware_id=tgt_id,
                    connection_type=connection_type,
                    source="discovery_inferred",
                )
            )
            created += 1
    db.flush()
    return created
