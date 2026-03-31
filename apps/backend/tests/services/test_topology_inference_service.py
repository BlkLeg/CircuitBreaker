from app.services.topology_inference_service import (
    _gateway_score,
    apply_inferred_topology,
    infer_connections,
)


def _n(id: int, role: str, ip: str | None = None) -> dict:
    return {"id": id, "role": role, "ip_address": ip}


def test_firewall_router_switch_chain():
    edges = infer_connections(
        [
            _n(1, "firewall", "192.168.1.1"),
            _n(2, "router", "192.168.1.2"),
            _n(3, "switch", "192.168.1.3"),
        ]
    )
    assert (1, 2) in edges
    assert (2, 3) in edges


def test_endpoints_connect_to_switch():
    edges = infer_connections(
        [
            _n(1, "switch", "192.168.1.1"),
            _n(2, "compute", "192.168.1.10"),
            _n(3, "compute", "192.168.1.11"),
        ]
    )
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_no_chain_nodes_star_fallback():
    # Task 9: when no router/switch/firewall exists, star-connect to the hub node.
    # Two compute nodes on the same subnet → hub (node 1) connects to node 2.
    edges = infer_connections(
        [
            _n(1, "compute", "192.168.1.10"),
            _n(2, "compute", "192.168.1.11"),
        ]
    )
    assert (1, 2) in edges


def test_multiple_subnets_are_independent():
    edges = infer_connections(
        [
            _n(1, "switch", "192.168.1.1"),
            _n(2, "compute", "192.168.1.10"),
            _n(3, "switch", "10.0.0.1"),
            _n(4, "compute", "10.0.0.10"),
        ]
    )
    assert (1, 2) in edges
    assert (3, 4) in edges
    assert (1, 4) not in edges
    assert (3, 2) not in edges


def test_multiple_switches_distribute_endpoints():
    edges = infer_connections(
        [
            _n(1, "router", "192.168.1.1"),
            _n(2, "switch", "192.168.1.2"),
            _n(3, "switch", "192.168.1.3"),
            _n(4, "compute", "192.168.1.10"),
            _n(5, "compute", "192.168.1.11"),
        ]
    )
    assert (1, 2) in edges
    assert (1, 3) in edges
    # endpoints distributed across switches
    assert (2, 4) in edges or (3, 4) in edges
    assert (2, 5) in edges or (3, 5) in edges


def test_nodes_with_no_ip_grouped_together():
    edges = infer_connections(
        [
            _n(1, "switch", None),
            _n(2, "compute", None),
        ]
    )
    assert (1, 2) in edges


def test_router_only_with_endpoints():
    edges = infer_connections(
        [
            _n(1, "router", "192.168.1.1"),
            _n(2, "server", "192.168.1.10"),
            _n(3, "compute", "192.168.1.11"),
        ]
    )
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_placeholder_gateway_connects_to_correct_subnet():
    # Placeholder has ip=None but subnet="10.10.10" — must group with real nodes
    nodes = [
        {"id": 99, "ip_address": None, "role": "router", "subnet": "10.10.10"},
        _n(1, "hypervisor", "10.10.10.3"),
        _n(2, "hypervisor", "10.10.10.4"),
        _n(3, "server", "10.10.10.5"),
    ]
    edges = infer_connections(nodes)
    assert (99, 1) in edges
    assert (99, 2) in edges
    assert (99, 3) in edges


def test_infer_connections_basic_chain():
    """Router anchors endpoints in the same /24."""
    nodes = [
        _n(1, "router", "192.168.1.1"),
        _n(2, "server", "192.168.1.10"),
        _n(3, "server", "192.168.1.11"),
    ]
    edges = infer_connections(nodes)
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_infer_connections_no_chain_star_fallback():
    # When all nodes score 0 (no IPAM signal), star from the first by rank.
    # Using .10/.11/.12 — none of these are .1/.2/.254/.126.
    edges = infer_connections(
        [
            _n(1, "compute", "192.168.1.10"),
            _n(2, "compute", "192.168.1.11"),
            _n(3, "compute", "192.168.1.12"),
        ]
    )
    # All score 0 → fallback: node 1 is hub
    assert len(edges) == 2
    assert all(1 in (src, tgt) for src, tgt in edges)


def test_infer_connections_no_chain_single_device_no_edges():
    """Single device with no chain produces no edges."""
    nodes = [_n(1, "misc", "10.0.0.1")]
    edges = infer_connections(nodes)
    assert edges == []


def test_infer_connections_switch_anchors_endpoints():
    """Endpoints connect to switch, not router."""
    nodes = [
        _n(1, "firewall", "172.16.0.1"),
        _n(2, "switch", "172.16.0.2"),
        _n(3, "server", "172.16.0.10"),
        _n(4, "server", "172.16.0.11"),
    ]
    edges = infer_connections(nodes)
    # switch -> endpoints
    assert (2, 3) in edges
    assert (2, 4) in edges
    # firewall -> switch (chain)
    assert (1, 2) in edges


def test_infer_connections_multi_subnet():
    """Nodes on different /24 subnets are inferred independently."""
    nodes = [
        _n(1, "router", "192.168.1.1"),
        _n(2, "server", "192.168.1.10"),
        _n(3, "router", "10.0.0.1"),
        _n(4, "server", "10.0.0.10"),
    ]
    edges = infer_connections(nodes)
    assert (1, 2) in edges
    assert (3, 4) in edges
    # No cross-subnet edges
    assert (1, 4) not in edges
    assert (3, 2) not in edges


def test_gateway_score_values():
    assert _gateway_score("192.168.1.1") == 10
    assert _gateway_score("192.168.1.254") == 5
    assert _gateway_score("192.168.1.2") == 2
    assert _gateway_score("192.168.1.126") == 1
    assert _gateway_score("192.168.1.50") == 0
    assert _gateway_score(None) == 0


def test_infer_connections_ipam_root_dot1():
    """When no chain roles exist, the .1 node becomes the root."""
    edges = infer_connections(
        [
            _n(1, "server", "10.0.1.1"),
            _n(2, "server", "10.0.1.50"),
            _n(3, "server", "10.0.1.51"),
        ]
    )
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_infer_connections_multi_level_tree():
    """.1 and .254 form a 2-level chain; score-0 nodes are endpoints off .254."""
    edges = infer_connections(
        [
            _n(1, "server", "192.168.5.1"),  # score 10
            _n(2, "server", "192.168.5.254"),  # score 5
            _n(3, "misc", "192.168.5.100"),  # score 0
            _n(4, "misc", "192.168.5.101"),  # score 0
        ]
    )
    assert (1, 2) in edges
    assert (2, 3) in edges
    assert (2, 4) in edges
    assert (1, 3) not in edges
    assert (1, 4) not in edges


def test_infer_connections_no_ipam_signal_unchanged():
    """When all nodes have score 0, the old star fallback is used (first by rank)."""
    edges = infer_connections(
        [
            _n(1, "server", "10.0.0.10"),
            _n(2, "misc", "10.0.0.20"),
            _n(3, "misc", "10.0.0.30"),
        ]
    )
    assert len(edges) == 2
    assert all(1 in (src, tgt) for src, tgt in edges)


def test_infer_connections_role_override_wins():
    """A misc node with role_overrides={"router"} becomes the chain root."""
    edges = infer_connections(
        [
            _n(1, "misc", "10.0.0.5"),
            _n(2, "misc", "10.0.0.10"),
            _n(3, "misc", "10.0.0.11"),
        ],
        role_overrides={1: "router"},
    )
    assert (1, 2) in edges
    assert (1, 3) in edges


def test_infer_connections_same_rank_ipam_tiebreak():
    """Two router-role nodes: .1 is upstream of .2 (same rank, gateway score breaks tie)."""
    edges = infer_connections(
        [
            _n(1, "router", "10.0.0.2"),  # rank 2, score 2 — lower score
            _n(2, "router", "10.0.0.1"),  # rank 2, score 10 — HIGHER score, should be upstream
            _n(3, "server", "10.0.0.50"),
        ]
    )
    assert (2, 1) in edges
    assert (1, 3) in edges


def test_apply_inferred_topology_role_override_writes_db_and_creates_edges(db_session):
    """role_overrides writes the role to Hardware.role AND makes that node the chain root."""
    from app.db.models import Hardware, HardwareConnection, Topology, TopologyNode

    topo = Topology(name="Test Map", is_default=True)
    db_session.add(topo)
    db_session.flush()

    hw_root = Hardware(name="gw", ip_address="10.1.1.1", role="misc", source="discovery")
    hw_e1 = Hardware(name="e1", ip_address="10.1.1.10", role="misc", source="discovery")
    hw_e2 = Hardware(name="e2", ip_address="10.1.1.11", role="misc", source="discovery")
    hw_e3 = Hardware(name="e3", ip_address="10.1.1.12", role="misc", source="discovery")
    db_session.add_all([hw_root, hw_e1, hw_e2, hw_e3])
    db_session.flush()

    for hw in [hw_root, hw_e1, hw_e2, hw_e3]:
        db_session.add(TopologyNode(topology_id=topo.id, entity_type="hardware", entity_id=hw.id))
    db_session.flush()

    all_ids = [hw_root.id, hw_e1.id, hw_e2.id, hw_e3.id]

    edges_created = apply_inferred_topology(
        db_session,
        all_ids,
        topo.id,
        actor="test",
        role_overrides={hw_root.id: "router"},
    )

    db_session.expire_all()

    assert db_session.get(Hardware, hw_root.id).role == "router"
    assert edges_created == 3
    connections = db_session.query(HardwareConnection).all()
    src_ids = {c.source_hardware_id for c in connections}
    assert hw_root.id in src_ids, "hw_root must be the source of all edges"
