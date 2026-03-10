"""Graph layout registry.

Provides a canonical list of layout descriptors used by the frontend
layout selector.  Each entry describes an engine that the frontend
``utils/layouts.js`` knows how to apply.
"""

from __future__ import annotations

LAYOUTS: list[dict] = [
    {
        "id": "dagre",
        "label": "Dagre (Hierarchical)",
        "description": "Top-down hierarchy using the Dagre algorithm. Best for parent-child relationships.",
        "category": "standard",
        "icon": "layout-dashboard",
    },
    {
        "id": "force",
        "label": "Force Directed",
        "description": "Physics-based layout that clusters connected nodes. Good for organic topology views.",
        "category": "standard",
        "icon": "atom",
    },
    {
        "id": "tree",
        "label": "Tree",
        "description": "Left-to-right tree layout. Ideal for strict parent-child hierarchies.",
        "category": "standard",
        "icon": "git-branch",
    },
    {
        "id": "manual",
        "label": "Manual / Saved",
        "description": "Restore the last manually saved node positions.",
        "category": "standard",
        "icon": "move",
    },
    {
        "id": "hierarchical_network",
        "label": "Network Hierarchy",
        "description": "Networks at the top, hardware in the middle, services at the bottom.",
        "category": "advanced",
        "icon": "layers",
        "docker_optimised": False,
    },
    {
        "id": "radial",
        "label": "Radial Services",
        "description": "Service-centric radial layout. Core services in the centre, dependencies as spokes.",
        "category": "advanced",
        "icon": "radar",
        "docker_optimised": True,
    },
    {
        "id": "elk_layered",
        "label": "VLAN Flow",
        "description": "Left-to-right layered layout (ELK). Ideal for visualising VLAN / network segmentation.",
        "category": "advanced",
        "icon": "arrow-right-circle",
        "docker_optimised": False,
    },
    {
        "id": "circular_cluster",
        "label": "Docker Clusters",
        "description": "Docker networks arranged as circular clusters with containers as spokes.",
        "category": "advanced",
        "icon": "circle-dot",
        "docker_optimised": True,
    },
    {
        "id": "grid_rack",
        "label": "Rack Grid",
        "description": "Grid layout respecting rack unit (U) positions. Best when all nodes are rack-mounted.",
        "category": "advanced",
        "icon": "server",
        "docker_optimised": False,
    },
    {
        "id": "concentric",
        "label": "Concentric Rings",
        "description": "Onion-ring layout: external nodes → hardware → services → storage, from outside in.",
        "category": "advanced",
        "icon": "circle",
        "docker_optimised": False,
    },
]

PRESETS: list[dict] = [
    {
        "id": "docker_stacks",
        "label": "Docker Stacks",
        "description": "Circular cluster layout with Docker networks highlighted.",
        "layout": "circular_cluster",
        "filter": "docker",
        "icon": "container",
    },
    {
        "id": "service_mesh",
        "label": "Service Mesh",
        "description": "Radial layout with published_port edges emphasised.",
        "layout": "radial",
        "filter": None,
        "icon": "share-2",
    },
]


def get_layouts() -> dict:
    return {"layouts": LAYOUTS, "presets": PRESETS}
