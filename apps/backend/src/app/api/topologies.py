"""Topologies API — v0.2.0

Explicit, named topology snapshots per team. Each topology has nodes
(entity references with x/y positions) and edges (connections).

Routes:
    GET  /api/v1/topologies                  — list topologies
    POST /api/v1/topologies                  — create topology
    GET  /api/v1/topologies/{id}             — get topology detail
    PUT  /api/v1/topologies/{id}             — update topology metadata
    DELETE /api/v1/topologies/{id}           — delete topology
    GET  /api/v1/topologies/{id}/graph       — Cytoscape JSON export
    PUT  /api/v1/topologies/{id}/nodes       — bulk-replace node positions
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import Topology, TopologyEdge, TopologyNode
from app.db.session import get_db

router = APIRouter(tags=["topologies"])
_logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────────


class TopologyCreate(BaseModel):
    name: str
    team_id: int | None = None
    is_default: bool = False


class TopologyUpdate(BaseModel):
    name: str | None = None
    is_default: bool | None = None


class NodePosition(BaseModel):
    entity_type: str  # hardware | service | network | external_node
    entity_id: int
    x: float | None = None
    y: float | None = None
    size: float | None = None
    extra: dict[str, Any] | None = None


class BulkNodesRequest(BaseModel):
    nodes: list[NodePosition]


# ── Helpers ────────────────────────────────────────────────────────────────


def _topology_or_404(topology_id: int, db: Session) -> Topology:
    t = db.query(Topology).filter(Topology.id == topology_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Topology not found")
    return t


def _node_to_cytoscape(node: TopologyNode) -> dict[str, Any]:
    return {
        "group": "nodes",
        "data": {
            "id": f"{node.entity_type}-{node.entity_id}",
            "entity_type": node.entity_type,
            "entity_id": node.entity_id,
            "node_id": node.id,
        },
        "position": {"x": node.x or 0, "y": node.y or 0},
    }


def _edge_to_cytoscape(edge: TopologyEdge, nodes: list[TopologyNode]) -> dict[str, Any]:
    node_map = {n.id: n for n in nodes}
    src = node_map.get(edge.source_node_id)
    tgt = node_map.get(edge.target_node_id)
    return {
        "group": "edges",
        "data": {
            "id": f"edge-{edge.id}",
            "source": f"{src.entity_type}-{src.entity_id}" if src else str(edge.source_node_id),
            "target": f"{tgt.entity_type}-{tgt.entity_id}" if tgt else str(edge.target_node_id),
            "edge_type": edge.edge_type,
        },
    }


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("")
def list_topologies(
    team_id: int | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(Topology)
    if team_id is not None:
        q = q.filter(Topology.team_id == team_id)
    topologies = q.order_by(Topology.id).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "team_id": t.team_id,
            "is_default": t.is_default,
            "node_count": len(t.nodes),
            "edge_count": len(t.edges),
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        }
        for t in topologies
    ]


@router.post("", status_code=201)
def create_topology(
    payload: TopologyCreate,
    db: Session = Depends(get_db),
) -> dict:
    topology = Topology(
        name=payload.name,
        team_id=payload.team_id,
        is_default=payload.is_default,
    )
    db.add(topology)
    db.commit()
    db.refresh(topology)
    _logger.info("Created topology id=%d name=%s", topology.id, topology.name)
    return {"id": topology.id, "name": topology.name, "team_id": topology.team_id}


@router.get("/{topology_id}")
def get_topology(topology_id: int, db: Session = Depends(get_db)) -> dict:
    t = _topology_or_404(topology_id, db)
    return {
        "id": t.id,
        "name": t.name,
        "team_id": t.team_id,
        "is_default": t.is_default,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "nodes": [
            {
                "id": n.id,
                "entity_type": n.entity_type,
                "entity_id": n.entity_id,
                "x": n.x,
                "y": n.y,
                "size": n.size,
                "extra": n.extra,
            }
            for n in t.nodes
        ],
        "edges": [
            {
                "id": e.id,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "edge_type": e.edge_type,
            }
            for e in t.edges
        ],
    }


@router.put("/{topology_id}")
def update_topology(
    topology_id: int,
    payload: TopologyUpdate,
    db: Session = Depends(get_db),
) -> dict:
    t = _topology_or_404(topology_id, db)
    if payload.name is not None:
        t.name = payload.name
    if payload.is_default is not None:
        t.is_default = payload.is_default
    db.commit()
    db.refresh(t)
    return {"id": t.id, "name": t.name, "is_default": t.is_default}


@router.delete("/{topology_id}", status_code=204)
def delete_topology(topology_id: int, db: Session = Depends(get_db)) -> None:
    t = _topology_or_404(topology_id, db)
    db.delete(t)
    db.commit()


@router.get("/{topology_id}/graph")
def export_cytoscape(topology_id: int, db: Session = Depends(get_db)) -> dict:
    """Export topology as Cytoscape.js-compatible JSON."""
    t = _topology_or_404(topology_id, db)
    nodes = list(t.nodes)
    edges = list(t.edges)
    elements = [_node_to_cytoscape(n) for n in nodes] + [
        _edge_to_cytoscape(e, nodes) for e in edges
    ]
    return {
        "topology": {"id": t.id, "name": t.name, "team_id": t.team_id},
        "elements": elements,
    }


@router.put("/{topology_id}/nodes", status_code=200)
def bulk_update_nodes(
    topology_id: int,
    payload: BulkNodesRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Replace all node positions in the topology (bulk upsert by entity_type+entity_id)."""
    t = _topology_or_404(topology_id, db)

    # Delete existing nodes (cascade also removes edges referencing them)
    for node in list(t.nodes):
        db.delete(node)
    db.flush()

    # Insert new node positions
    new_nodes: list[TopologyNode] = []
    for pos in payload.nodes:
        node = TopologyNode(
            topology_id=topology_id,
            entity_type=pos.entity_type,
            entity_id=pos.entity_id,
            x=pos.x,
            y=pos.y,
            size=pos.size,
            extra=pos.extra,
        )
        db.add(node)
        new_nodes.append(node)

    db.commit()
    return {"topology_id": topology_id, "node_count": len(new_nodes)}
