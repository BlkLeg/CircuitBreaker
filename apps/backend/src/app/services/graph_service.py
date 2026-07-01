import json
import logging
import math
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import GraphLayout, HardwareConnection

logger = logging.getLogger(__name__)


def create_edge(
    db: Session,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    edge_kind: str = "connects_to",
) -> None:
    """Create a graph edge between two entities.

    Currently supports hardware→hardware edges via the ``hardware_connections``
    table.  Other source/target type combinations are logged as a warning and
    skipped rather than raising, so callers (e.g. ``_sync_port_edges``) remain
    crash-free when topology features are partially implemented. (#74)
    """
    if source_type == "hardware" and target_type == "hardware":
        try:
            conn = HardwareConnection(
                source_hardware_id=source_id,
                target_hardware_id=target_id,
                connection_type="ethernet",
                source="port_map",
            )
            db.add(conn)
            db.flush()
        except IntegrityError:
            # UniqueConstraint violation — edge already exists, that's fine.
            db.rollback()
    else:
        logger.debug(
            "create_edge: unsupported edge type %s→%s (kind=%s) — skipping",
            source_type,
            target_type,
            edge_kind,
        )




def save_layout(db: Session, name: str, layout_data: str | dict) -> None:
    """Save positions to the graph layout table (server-side)."""
    parsed: dict
    if isinstance(layout_data, str):
        try:
            parsed = json.loads(layout_data)
        except json.JSONDecodeError:
            parsed = {}
    else:
        parsed = layout_data

    layout = db.query(GraphLayout).filter(GraphLayout.name == name).first()
    if layout:
        layout.layout_data = parsed
    else:
        layout = GraphLayout(name=name, layout_data=parsed)
        db.add(layout)
    db.commit()


def _extract_layout_nodes(layout_data: dict | str | None) -> list[dict]:
    """Extract node position records from supported layout formats.

    Supports:
    - {"nodes": {"node-id": {"x": ..., "y": ...}}, "edges": {...}}
    - {"node-id": {"x": ..., "y": ...}} (legacy)
    - {"nodes": [{"id": "...", "position": {"x": ..., "y": ...}}, ...]}
    """
    if not layout_data:
        return []

    if isinstance(layout_data, dict):
        parsed = layout_data
    else:
        try:
            parsed = json.loads(layout_data)
        except json.JSONDecodeError:
            return []

    raw_nodes: Any = parsed.get("nodes", parsed) if isinstance(parsed, dict) else []
    nodes: list[dict] = []

    if isinstance(raw_nodes, list):
        for item in raw_nodes:
            if not isinstance(item, dict):
                continue
            position = item.get("position")
            if (
                isinstance(position, dict)
                and position.get("x") is not None
                and position.get("y") is not None
            ):
                nodes.append({"position": {"x": position.get("x"), "y": position.get("y")}})
        return nodes

    if isinstance(raw_nodes, dict):
        for node_id, value in raw_nodes.items():
            if not isinstance(value, dict):
                continue
            if value.get("x") is not None and value.get("y") is not None:
                nodes.append(
                    {"id": node_id, "position": {"x": value.get("x"), "y": value.get("y")}}
                )
                continue
            position = value.get("position")
            if (
                isinstance(position, dict)
                and position.get("x") is not None
                and position.get("y") is not None
            ):
                nodes.append(
                    {"id": node_id, "position": {"x": position.get("x"), "y": position.get("y")}}
                )

    return nodes


def overlaps(test_x: float, test_y: float, nodes: list[dict], threshold: float = 120.0) -> bool:
    """Check if the given coordinate overlaps with any existing nodes within the threshold."""
    for node in nodes:
        pos = node.get("position", {})
        px = pos.get("x")
        py = pos.get("y")
        if px is not None and py is not None:
            dist = math.hypot(test_x - px, test_y - py)
            if dist < threshold:
                return True
    return False


def place_node_safe(db: Session, node_id: str, environment: str = "default") -> dict:
    layout_name = f"env_{environment}" if environment and environment != "default" else "default"
    layout = db.query(GraphLayout).filter(GraphLayout.name == layout_name).first()

    nodes = _extract_layout_nodes(layout.layout_data if layout else None)

    # Calculate centroid of existing nodes, or use default viewport center
    if nodes:
        xs = [n["position"]["x"] for n in nodes if n["position"].get("x") is not None]
        ys = [n["position"]["y"] for n in nodes if n["position"].get("y") is not None]
        cx = sum(xs) / len(xs) if xs else 450.0
        cy = sum(ys) / len(ys) if ys else 320.0
    else:
        cx, cy = 450.0, 320.0

    # Grid-spiral placement: expanding from centroid, 160px spacing
    spacing = 160
    for ring in range(20):  # max 20 rings = 3200px
        for dx in range(-ring, ring + 1):
            for dy in range(-ring, ring + 1):
                if abs(dx) != ring and abs(dy) != ring:
                    continue  # only check perimeter of this ring
                test_x = cx + dx * spacing
                test_y = cy + dy * spacing
                if not overlaps(test_x, test_y, nodes, threshold=120.0):
                    return {"x": round(test_x, 1), "y": round(test_y, 1)}

    return {"x": cx, "y": cy}
