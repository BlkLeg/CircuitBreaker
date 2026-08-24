"""Integration tests for the standalone external-node relationship deletes.

INC-05: `_rel_router` in `api/external_nodes.py` was defined and never mounted,
so `DELETE /api/v1/external-node-networks/{relation_id}` answered 404 and
unlinking an external node from a network was impossible in the product. The
frontend callers are `externalNodesApi.removeNetwork` (`api/client.jsx`), used
by `pages/ExternalNodesPage.jsx` and `components/map/linkMutations.js`; the path
they send is pinned from the frontend side by
`__tests__/external-nodes-api.test.js`.
"""

from __future__ import annotations

import pytest

from app.db.models import ExternalNodeNetwork


@pytest.fixture
def network_link(db_session, factories):
    node = factories.external_node()
    net = factories.network()
    link = ExternalNodeNetwork(external_node_id=node.id, network_id=net.id, link_type="vpn")
    db_session.add(link)
    db_session.flush()
    return link


@pytest.mark.asyncio
async def test_unlink_network_removes_the_link(client, auth_headers, db_session, network_link):
    relation_id = network_link.id

    resp = await client.delete(
        f"/api/v1/external-node-networks/{relation_id}", headers=auth_headers
    )

    assert resp.status_code == 204
    assert db_session.get(ExternalNodeNetwork, relation_id) is None


@pytest.mark.asyncio
async def test_unlink_network_unknown_relation_is_404(client, auth_headers):
    resp = await client.delete("/api/v1/external-node-networks/999999", headers=auth_headers)

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unlink_network_rejects_a_viewer(client, viewer_headers, db_session, network_link):
    relation_id = network_link.id

    resp = await client.delete(
        f"/api/v1/external-node-networks/{relation_id}", headers=viewer_headers
    )

    assert resp.status_code == 403
    assert db_session.get(ExternalNodeNetwork, relation_id) is not None


@pytest.mark.asyncio
async def test_unlink_network_requires_authentication(client, db_session, network_link):
    resp = await client.delete(f"/api/v1/external-node-networks/{network_link.id}")

    assert resp.status_code == 401
    assert db_session.get(ExternalNodeNetwork, network_link.id) is not None
