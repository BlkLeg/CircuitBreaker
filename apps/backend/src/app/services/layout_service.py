"""
Subnet-grouped canvas layout for newly imported hardware nodes.

Groups nodes by /24 slice, places gateway/router at top-center of each group,
remaining nodes in rows of up to 5. Returns {hardware_id: {"x": float, "y": float}}.
"""

from __future__ import annotations

_GROUP_X_SPACING = 600
_NODE_X_SPACING = 200
_NODE_Y_SPACING = 180
_GROUP_Y_ORIGIN = 100
_GATEWAY_Y = 50
_OVERFLOW_X = 2000
_MAX_COLS = 5


def _subnet_key(ip: str | None) -> str | None:
    """Return the /24 prefix as 'A.B.C', or None if absent/malformed."""
    if not ip:
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    try:
        [int(p) for p in parts]
    except ValueError:
        return None
    return ".".join(parts[:3])


def _is_gateway(hw: dict) -> bool:
    return hw.get("role") in ("router", "gateway")


def compute_subnet_layout(hardware: list[dict]) -> dict[int, dict]:
    """
    hardware: list of dicts with keys: id (int), ip_address (str|None), role (str|None)
    Returns: {id: {"x": float, "y": float}}
    """
    if not hardware:
        return {}

    groups: dict[str, list[dict]] = {}
    overflow: list[dict] = []
    for hw in hardware:
        key = _subnet_key(hw.get("ip_address"))
        if key is None:
            overflow.append(hw)
        else:
            groups.setdefault(key, []).append(hw)

    positions: dict[int, dict] = {}
    col = 0

    for subnet_key in sorted(groups.keys()):
        nodes = groups[subnet_key]
        x_center = col * _GROUP_X_SPACING + 300

        gateways = [n for n in nodes if _is_gateway(n)]
        others = [n for n in nodes if not _is_gateway(n)]
        if not gateways and others:
            others_sorted = sorted(
                others, key=lambda n: int((n.get("ip_address") or "0.0.0.0").split(".")[-1])
            )
            gateways = [others_sorted[0]]
            others = others_sorted[1:]

        for gw in gateways:
            positions[gw["id"]] = {"x": float(x_center), "y": float(_GATEWAY_Y)}

        for idx, node in enumerate(others):
            row = idx // _MAX_COLS
            col_off = idx % _MAX_COLS
            x = x_center - (_MAX_COLS // 2) * _NODE_X_SPACING + col_off * _NODE_X_SPACING
            y = _GROUP_Y_ORIGIN + row * _NODE_Y_SPACING
            positions[node["id"]] = {"x": float(x), "y": float(y)}

        col += 1

    for idx, node in enumerate(overflow):
        positions[node["id"]] = {
            "x": float(_OVERFLOW_X),
            "y": float(_GROUP_Y_ORIGIN + idx * _NODE_Y_SPACING),
        }

    return positions
