"""
Tests for topology management endpoints:
  GET  /api/v1/topologies
  POST /api/v1/topologies
  PUT  /api/v1/topologies/{id}/nodes
  GET  /api/v1/graph/topology
  GET  /api/v1/graph/layout
"""

import pytest
from sqlalchemy import select

from app.db.models import TopologyNode

TOPOLOGIES_URL = "/api/v1/topologies"


@pytest.mark.asyncio
async def test_list_topologies_empty(client, auth_headers):
    """GET /topologies → 200 with an empty list when no topologies exist."""
    resp = await client.get(TOPOLOGIES_URL, headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_topology(client, auth_headers):
    """POST /topologies → 201 with id and name."""
    resp = await client.post(TOPOLOGIES_URL, json={"name": "home-lab"}, headers=auth_headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "home-lab"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_topologies_returns_created(client, auth_headers):
    """After creation, GET /topologies includes the new topology."""
    await client.post(TOPOLOGIES_URL, json={"name": "visible-topo"}, headers=auth_headers)
    resp = await client.get(TOPOLOGIES_URL, headers=auth_headers)
    names = [t["name"] for t in resp.json()]
    assert "visible-topo" in names


@pytest.mark.asyncio
async def test_bulk_nodes_creates_topology_node_rows(client, auth_headers, db_session, factories):
    """PUT /{id}/nodes bulk-replaces TopologyNode rows for valid entities."""
    hw = factories.hardware(name="topo-hw", ip_address="10.9.9.1")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "assign-test"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]

    payload = {"nodes": [{"entity_type": "hardware", "entity_id": hw.id, "x": 10, "y": 20}]}
    resp = await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["node_count"] == 1

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1
    assert nodes[0].entity_type == "hardware"
    assert nodes[0].entity_id == hw.id


@pytest.mark.asyncio
async def test_bulk_nodes_replaces_on_second_call(client, auth_headers, db_session, factories):
    """Calling PUT /nodes twice replaces (not duplicates) the node set."""
    hw = factories.hardware(name="idem-hw", ip_address="10.9.9.2")

    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "idem-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"nodes": [{"entity_type": "hardware", "entity_id": hw.id, "x": 0, "y": 0}]}

    await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)

    nodes = db_session.scalars(
        select(TopologyNode).where(TopologyNode.topology_id == topo_id)
    ).all()
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_bulk_nodes_accepts_unknown_entity_type(client, auth_headers):
    """Unknown entity_type is accepted (no server-side validation on type string)."""
    create_resp = await client.post(
        TOPOLOGIES_URL, json={"name": "skip-topo"}, headers=auth_headers
    )
    topo_id = create_resp.json()["id"]
    payload = {"nodes": [{"entity_type": "unicorn", "entity_id": 1}]}

    resp = await client.put(f"{TOPOLOGIES_URL}/{topo_id}/nodes", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["node_count"] == 1


@pytest.mark.asyncio
async def test_bulk_nodes_to_missing_topology(client, auth_headers):
    """PUT /nodes on a non-existent topology returns 404."""
    resp = await client.put(
        f"{TOPOLOGIES_URL}/99999/nodes",
        json={"nodes": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Graph topology endpoint — /api/v1/graph/topology
# ---------------------------------------------------------------------------

TOPOLOGY_URL = "/api/v1/graph/topology"
LAYOUT_URL = "/api/v1/graph/layout"


class TestGraphTopology:
    @pytest.mark.asyncio
    async def test_get_topology_empty(self, client, auth_headers):
        """GET /graph/topology returns graph data with nodes and edges keys."""
        resp = await client.get(TOPOLOGY_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert isinstance(body["nodes"], list)
        assert isinstance(body["edges"], list)

    @pytest.mark.asyncio
    async def test_get_topology_with_hardware(self, client, auth_headers, factories):
        """GET /graph/topology includes hardware nodes."""
        factories.hardware(name="topo-test-hw")
        resp = await client.get(TOPOLOGY_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        node_labels = [n.get("label", "") for n in body["nodes"]]
        # Hardware node should appear (label may include other info)
        assert any("topo-test-hw" in label for label in node_labels), (
            f"Hardware 'topo-test-hw' not found in topology nodes: {node_labels}"
        )

    @pytest.mark.asyncio
    async def test_get_topology_with_service(self, client, auth_headers, factories):
        """GET /graph/topology includes service nodes when include=services."""
        factories.service(name="topo-test-svc")
        resp = await client.get(
            TOPOLOGY_URL,
            headers=auth_headers,
            params={"include": "services"},
        )
        assert resp.status_code == 200
        body = resp.json()
        node_ids = [n.get("id", "") for n in body["nodes"]]
        # Service nodes may use prefixed IDs like "svc-1" or "service-1"
        assert any("svc" in str(nid) or "service" in str(nid) for nid in node_ids), (
            f"Service node not found in topology: {node_ids}"
        )

    @pytest.mark.asyncio
    async def test_get_topology_unauthenticated(self, client):
        """GET /graph/topology without auth returns 401."""
        resp = await client.get(TOPOLOGY_URL)
        assert resp.status_code == 401


class TestGraphETag:
    @pytest.mark.asyncio
    async def test_etag_returned_in_response(self, client, auth_headers):
        """GET /graph/topology returns ETag header."""
        resp = await client.get(TOPOLOGY_URL, headers=auth_headers)
        assert resp.status_code == 200
        assert "etag" in resp.headers, (
            f"ETag header missing from topology response. Headers: {dict(resp.headers)}"
        )

    @pytest.mark.asyncio
    async def test_etag_304_not_modified(self, client, auth_headers):
        """GET /graph/topology with matching If-None-Match returns 304."""
        # First request — get ETag
        resp1 = await client.get(TOPOLOGY_URL, headers=auth_headers)
        assert resp1.status_code == 200
        etag = resp1.headers["etag"]

        # Second request with If-None-Match
        resp2 = await client.get(
            TOPOLOGY_URL,
            headers={**auth_headers, "If-None-Match": etag},
        )
        assert resp2.status_code == 304, f"Expected 304 Not Modified, got {resp2.status_code}"

    @pytest.mark.asyncio
    async def test_etag_changes_after_data_mutation(self, client, auth_headers, factories):
        """ETag changes when underlying data changes."""
        resp1 = await client.get(TOPOLOGY_URL, headers=auth_headers)
        etag1 = resp1.headers["etag"]

        # Add hardware — should change the ETag
        factories.hardware(name="etag-change-hw")

        resp2 = await client.get(TOPOLOGY_URL, headers=auth_headers)
        etag2 = resp2.headers["etag"]
        assert etag1 != etag2, "ETag should change after adding hardware"


class TestGraphEnvironmentFilter:
    @pytest.mark.asyncio
    async def test_environment_filter_accepted(self, client, auth_headers):
        """GET /graph/topology with environment param is accepted."""
        resp = await client.get(
            TOPOLOGY_URL,
            headers=auth_headers,
            params={"environment": "production"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body

    @pytest.mark.asyncio
    async def test_include_filter(self, client, auth_headers):
        """GET /graph/topology with include param limits node types."""
        resp = await client.get(
            TOPOLOGY_URL,
            headers=auth_headers,
            params={"include": "hardware"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        # All nodes should be hardware type
        for node in body["nodes"]:
            node_id = node.get("id", "")
            assert "hardware" in str(node_id) or "hw" in str(node_id) or len(body["nodes"]) == 0


class TestGraphLayout:
    @pytest.mark.asyncio
    async def test_get_layout_default_empty(self, client, auth_headers):
        """GET /graph/layout returns null layout_data when no layout saved."""
        resp = await client.get(LAYOUT_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "layout_data" in body

    @pytest.mark.asyncio
    async def test_save_and_get_layout(self, client, auth_headers):
        """POST /graph/layout saves layout, GET retrieves it."""
        layout_data = '{"nodes": [{"id": "hw-1", "x": 100, "y": 200}]}'
        save_resp = await client.post(
            LAYOUT_URL,
            headers=auth_headers,
            json={"name": "default", "layout_data": layout_data},
        )
        assert save_resp.status_code == 200, (
            f"Layout save failed: {save_resp.status_code} {save_resp.text}"
        )

        get_resp = await client.get(LAYOUT_URL, headers=auth_headers)
        assert get_resp.status_code == 200
        body = get_resp.json()
        assert body["layout_data"] == layout_data

    @pytest.mark.asyncio
    async def test_save_layout_viewer_forbidden(self, client, viewer_headers):
        """Viewer cannot save layout (write operation)."""
        resp = await client.post(
            LAYOUT_URL,
            headers=viewer_headers,
            json={"name": "default", "layout_data": "{}"},
        )
        assert resp.status_code == 403, f"Viewer should not save layouts, got {resp.status_code}"


class TestGraphConnections:
    @pytest.mark.asyncio
    async def test_hardware_connections_appear_as_edges(
        self, client, auth_headers, factories, db_session
    ):
        """Hardware connections should appear as edges in the graph."""
        from app.db.models import HardwareConnection

        hw1 = factories.hardware(name="conn-hw-1")
        hw2 = factories.hardware(name="conn-hw-2")
        conn = HardwareConnection(
            source_hardware_id=hw1.id,
            target_hardware_id=hw2.id,
            connection_type="ethernet",
        )
        db_session.add(conn)
        db_session.flush()

        resp = await client.get(TOPOLOGY_URL, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Edges should contain the connection
        edge_sources = [e.get("source", "") for e in body["edges"]]
        edge_targets = [e.get("target", "") for e in body["edges"]]
        # The edge should reference both hardware nodes
        hw1_in_edges = any(str(hw1.id) in str(s) for s in edge_sources + edge_targets)
        hw2_in_edges = any(str(hw2.id) in str(s) for s in edge_sources + edge_targets)
        assert hw1_in_edges and hw2_in_edges, (
            f"Connection between hw1({hw1.id}) and hw2({hw2.id}) not found in edges"
        )

    @pytest.mark.asyncio
    async def test_service_dependencies_appear_as_edges(
        self, client, auth_headers, factories, db_session
    ):
        """Service dependencies should appear as edges in the graph."""
        from app.db.models import ServiceDependency

        svc1 = factories.service(name="dep-svc-1")
        svc2 = factories.service(name="dep-svc-2")
        dep = ServiceDependency(
            service_id=svc1.id,
            depends_on_id=svc2.id,
        )
        db_session.add(dep)
        db_session.flush()

        resp = await client.get(
            TOPOLOGY_URL,
            headers=auth_headers,
            params={"include": "services"},
        )
        assert resp.status_code == 200
        body = resp.json()
        edge_ids = [(e.get("source", ""), e.get("target", "")) for e in body["edges"]]
        svc1_found = any(str(svc1.id) in str(e) for pair in edge_ids for e in pair)
        svc2_found = any(str(svc2.id) in str(e) for pair in edge_ids for e in pair)
        assert svc1_found and svc2_found, (
            f"Service dependency between svc1({svc1.id}) and svc2({svc2.id}) "
            f"not found in edges: {edge_ids}"
        )
