"""
Phase 2 — Worker audit trail and SQL parameterization tests.

Validates:
- HTTP mutations produce audit log entries (via LoggingMiddleware)
- log_worker_audit() writes Log rows with category='worker'
- graph.py CTE edge preload returns valid data via expression API
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.security


class TestHTTPMutationAuditTrail:
    """Verify that HTTP mutations auto-log via LoggingMiddleware."""

    @pytest.mark.asyncio
    async def test_hardware_create_produces_audit_log(self, client, auth_headers, db_session):
        """POST /hardware → audit log entry with entity_type containing 'hardware'."""
        resp = await client.post(
            "/api/v1/hardware",
            headers=auth_headers,
            json={"name": "audit-test-hw", "role": "compute"},
        )
        assert resp.status_code in (200, 201), f"Create failed: {resp.text}"

        from app.db.models import Log

        logs = (
            db_session.execute(
                select(Log).where(
                    Log.action.ilike("%hardware%"),
                    Log.details.ilike("%audit-test-hw%"),
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) >= 1, "No audit log entry found for hardware creation"
        log = logs[0]
        assert log.actor_id is not None or log.actor is not None

    @pytest.mark.asyncio
    async def test_delete_produces_audit_log(self, client, auth_headers, db_session):
        """DELETE mutation → audit log entry."""
        # Create then delete a tag
        resp = await client.post(
            "/api/v1/tags",
            headers=auth_headers,
            json={"name": "audit-delete-test"},
        )
        assert resp.status_code in (200, 201), f"Tag create failed: {resp.text}"
        tag_id = resp.json().get("id")

        resp = await client.delete(
            f"/api/v1/tags/{tag_id}",
            headers=auth_headers,
        )
        assert resp.status_code in (200, 204), f"Tag delete failed: {resp.text}"

        from app.db.models import Log

        logs = (
            db_session.execute(
                select(Log).where(
                    Log.action.ilike("%tag%"),
                    Log.action.ilike("%delete%"),
                )
            )
            .scalars()
            .all()
        )
        assert len(logs) >= 1, "No audit log entry found for tag deletion"


class TestWorkerAuditHelper:
    """Verify log_worker_audit() writes correctly to the Log table."""

    def test_worker_audit_writes_log(self, setup_db):
        """log_worker_audit() writes a Log row with category='worker' and actor='system'."""
        from app.core.worker_audit import log_worker_audit

        log_worker_audit(
            action="test_worker_action",
            entity_type="test_entity",
            entity_id=42,
            details="unit test run",
            worker_name="test_worker",
        )

        # worker_audit uses its own SessionLocal, so query with a fresh session
        from app.db.models import Log
        from app.db.session import SessionLocal

        with SessionLocal() as db:
            log = db.execute(
                select(Log).where(Log.action == "test_worker_action")
            ).scalar_one_or_none()

        assert log is not None, "Worker audit log entry not found"
        assert log.category == "worker"
        assert log.actor == "system"
        assert log.entity_type == "test_entity"
        assert log.entity_id == 42
        assert "test_worker" in (log.details or "")

    def test_worker_audit_never_raises(self, setup_db, monkeypatch):
        """log_worker_audit() must never crash — even if write_log is broken."""
        import app.services.log_service as log_svc

        def _broken_write_log(**kwargs):
            raise RuntimeError("Simulated write_log failure")

        monkeypatch.setattr(log_svc, "write_log", _broken_write_log)

        from app.core.worker_audit import log_worker_audit

        # Must not raise
        log_worker_audit(action="should_not_crash", worker_name="test")


class TestGraphCTEExpressionAPI:
    """Verify graph.py CTE conversion produces valid results."""

    def test_preload_edge_maps_returns_dict(self, db_session):
        """_preload_edge_maps should return a dict without error."""
        from app.api.graph import _preload_edge_maps

        result = _preload_edge_maps(db_session)
        assert isinstance(result, dict)
        # All keys should be known edge types
        valid_types = {"hn", "cn", "hh", "np", "dep", "ss", "sm", "extnet", "svcext", "hcm"}
        for key in result:
            assert key in valid_types, f"Unexpected edge type: {key}"

    def test_preload_edge_maps_with_data(self, db_session):
        """Insert edge data and verify the CTE returns it."""
        from app.db.models import Hardware, HardwareConnection

        # Create two hardware nodes
        hw1 = Hardware(name="cte-test-1", role="compute")
        hw2 = Hardware(name="cte-test-2", role="compute")
        db_session.add_all([hw1, hw2])
        db_session.flush()

        # Create a hardware connection
        conn = HardwareConnection(
            source_hardware_id=hw1.id,
            target_hardware_id=hw2.id,
            connection_type="ethernet",
            bandwidth_mbps=1000,
        )
        db_session.add(conn)
        db_session.flush()

        from app.api.graph import _preload_edge_maps

        result = _preload_edge_maps(db_session)
        hh_edges = result.get("hh", [])
        assert len(hh_edges) >= 1, "Expected at least one 'hh' edge"
        # Find our edge
        found = any(src == hw1.id and tgt == hw2.id for src, tgt, *_ in hh_edges)
        assert found, f"Expected edge {hw1.id}->{hw2.id} in hh edges"

    def test_preload_edge_maps_null_columns(self, db_session):
        """NetworkPeer edges use has_conn=False/has_bw=False — verify nulls are handled."""
        from app.db.models import Network, NetworkPeer

        net1 = Network(name="cte-net-1", cidr="10.0.1.0/24")
        net2 = Network(name="cte-net-2", cidr="10.0.2.0/24")
        db_session.add_all([net1, net2])
        db_session.flush()

        peer = NetworkPeer(network_a_id=net1.id, network_b_id=net2.id)
        db_session.add(peer)
        db_session.flush()

        from app.api.graph import _preload_edge_maps

        result = _preload_edge_maps(db_session)
        np_edges = result.get("np", [])
        assert len(np_edges) >= 1, "Expected at least one 'np' edge"
        found = [
            (src, tgt, conn_type, bw, row_id)
            for src, tgt, conn_type, bw, row_id in np_edges
            if src == net1.id and tgt == net2.id
        ]
        assert len(found) == 1, f"Expected peer edge {net1.id}->{net2.id}"
        _, _, conn_type, bw, _ = found[0]
        assert conn_type is None, f"Expected null connection_type, got {conn_type}"
        assert bw is None, f"Expected null bandwidth_mbps, got {bw}"
