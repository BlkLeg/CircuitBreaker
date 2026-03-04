import json
import logging
import math
from typing import Any, Optional
from sqlalchemy.orm import Session
from app.db.models import GraphLayout

logger = logging.getLogger(__name__)


def _extract_layout_nodes(layout_data: str | None) -> list[dict]:
    """Extract node position records from supported layout formats.

    Supports:
    - {"nodes": {"node-id": {"x": ..., "y": ...}}, "edges": {...}}
    - {"node-id": {"x": ..., "y": ...}} (legacy)
    - {"nodes": [{"id": "...", "position": {"x": ..., "y": ...}}, ...]}
    """
    if not layout_data:
        return []

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
            if isinstance(position, dict) and position.get("x") is not None and position.get("y") is not None:
                nodes.append({"position": {"x": position.get("x"), "y": position.get("y")}})
        return nodes

    if isinstance(raw_nodes, dict):
        for node_id, value in raw_nodes.items():
            if not isinstance(value, dict):
                continue
            if value.get("x") is not None and value.get("y") is not None:
                nodes.append({"id": node_id, "position": {"x": value.get("x"), "y": value.get("y")}})
                continue
            position = value.get("position")
            if isinstance(position, dict) and position.get("x") is not None and position.get("y") is not None:
                nodes.append({"id": node_id, "position": {"x": position.get("x"), "y": position.get("y")}})

    return nodes

def overlaps(test_x: float, test_y: float, nodes: list[dict], threshold: float = 60.0) -> bool:
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

def jitter_if_collides(candidate: dict, nodes: list[dict]) -> Optional[dict]:
    """Find a safe position by trying angles radially outwards."""
    jitter_radius = 60  # 1.5x node size approximation
    for angle_deg in range(0, 360, 15):
        angle_rad = math.radians(angle_deg)
        test_x = candidate["x"] + jitter_radius * math.cos(angle_rad)
        test_y = candidate["y"] + jitter_radius * math.sin(angle_rad)
        if not overlaps(test_x, test_y, nodes, threshold=60.0):
            return {"x": round(test_x, 1), "y": round(test_y, 1)}
    return None

def place_node_safe(db: Session, node_id: str, environment: str = "default") -> dict:
    layout_name = f"env_{environment}" if environment and environment != "default" else "default"
    layout = db.query(GraphLayout).filter(GraphLayout.name == layout_name).first()
    
    nodes = _extract_layout_nodes(layout.layout_data if layout else None)

    # Basic bounding box fallback center if no intelligent layout algorithm is available on backend
    center_x, center_y = 450.0, 320.0
    candidate = {"x": center_x, "y": center_y}
    
    for attempt in range(5):
        if not overlaps(candidate["x"], candidate["y"], nodes):
            return candidate
        safe_pos = jitter_if_collides(candidate, nodes)
        if safe_pos:
            return safe_pos
        # Increase jitter radius incrementally if needed
        candidate["x"] += 20
        candidate["y"] += 20

    return {"x": 50.0, "y": 50.0}  # Ultimate fallback corner
