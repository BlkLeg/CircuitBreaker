"""Strict parsing and allowlists for the portable inventory format."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.schemas.inventory_transfer import PortableInventory

MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 10_000

ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "hardware": (
        "id",
        "name",
        "hostname",
        "role",
        "vendor",
        "model",
        "cpu",
        "memory_gb",
        "location",
        "notes",
        "ip_address",
        "wan_uplink",
        "cpu_brand",
        "os_version",
        "software_platform",
        "status",
    ),
    "compute_units": (
        "id",
        "name",
        "kind",
        "hardware_id",
        "os",
        "icon_slug",
        "cpu_cores",
        "cpu_brand",
        "memory_mb",
        "disk_gb",
        "ip_address",
        "environment",
        "notes",
        "status",
    ),
    "services": (
        "id",
        "name",
        "slug",
        "compute_id",
        "hardware_id",
        "icon_slug",
        "category",
        "url",
        "ports",
        "description",
        "environment",
        "status",
        "ip_address",
    ),
    "storage": (
        "id",
        "name",
        "kind",
        "hardware_id",
        "capacity_gb",
        "used_gb",
        "path",
        "protocol",
        "notes",
    ),
    "networks": (
        "id",
        "name",
        "cidr",
        "vlan_id",
        "gateway",
        "description",
        "gateway_hardware_id",
    ),
    "misc_items": ("id", "name", "kind", "url", "description"),
    "docs": ("id", "title", "body_md", "body_html"),
    "tags": ("id", "name", "color"),
    "hardware_clusters": ("id", "name", "description", "environment", "location"),
    "external_nodes": (
        "id",
        "name",
        "provider",
        "kind",
        "region",
        "ip_address",
        "icon_slug",
        "notes",
        "environment",
    ),
}

RELATIONSHIP_FIELDS: dict[str, tuple[str, ...]] = {
    "entity_tags": ("entity_type", "entity_id", "tag_id"),
    "entity_docs": ("entity_type", "entity_id", "doc_id"),
    "service_dependencies": ("service_id", "depends_on_id", "connection_type", "bandwidth_mbps"),
    "service_storage": ("service_id", "storage_id", "purpose", "connection_type", "bandwidth_mbps"),
    "service_misc": ("service_id", "misc_id", "purpose", "connection_type", "bandwidth_mbps"),
    "hardware_networks": (
        "hardware_id",
        "network_id",
        "ip_address",
        "connection_type",
        "bandwidth_mbps",
    ),
    "compute_networks": (
        "compute_id",
        "network_id",
        "ip_address",
        "connection_type",
        "bandwidth_mbps",
    ),
    "hardware_connections": (
        "source_hardware_id",
        "target_hardware_id",
        "connection_type",
        "bandwidth_mbps",
        "source_port",
        "target_port",
        "source",
    ),
    "hardware_cluster_members": ("cluster_id", "hardware_id", "role"),
    "external_node_networks": ("external_node_id", "network_id", "link_type", "notes"),
    "service_external_nodes": ("service_id", "external_node_id", "purpose"),
}


def normalize_legacy_v2(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "circuitbreaker.inventory",
        "version": 1,
        "exported_at": data.get("exported_at") or datetime.now(UTC).isoformat(),
        "manifest": {
            "included": list(ENTITY_FIELDS) + list(RELATIONSHIP_FIELDS),
            "excluded": [
                "users",
                "credentials",
                "settings",
                "operational_history",
                "telemetry",
                "map_layouts",
                "uploaded_files",
            ],
        },
        "entities": {name: data.get(name, []) for name in ENTITY_FIELDS},
        "relationships": {name: data.get(name, []) for name in RELATIONSHIP_FIELDS},
    }


def _validate_records(
    groups: dict[str, list[dict[str, Any]]], allowlists: dict[str, tuple[str, ...]]
) -> int:
    unknown_groups = set(groups) - set(allowlists)
    if unknown_groups:
        raise ValueError(f"Unsupported inventory sections: {', '.join(sorted(unknown_groups))}")
    count = 0
    for group, rows in groups.items():
        if not isinstance(rows, list):
            raise ValueError(f"Inventory section {group} must be a list")
        allowed = set(allowlists[group])
        source_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"Inventory section {group} contains a non-object record")
            unknown = set(row) - allowed
            if unknown:
                raise ValueError(f"Unsupported fields in {group}: {', '.join(sorted(unknown))}")
            if group in ENTITY_FIELDS:
                source_id = row.get("id")
                if not isinstance(source_id, int) or source_id < 1 or source_id in source_ids:
                    raise ValueError(f"Every {group} record needs a unique positive integer id")
                source_ids.add(source_id)
            count += 1
    return count


def parse_inventory_document(raw: bytes | dict[str, Any]) -> PortableInventory:
    """Parse a bounded document without constructing ORM objects from input."""
    if isinstance(raw, bytes):
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise ValueError("Inventory document exceeds the 5 MiB limit")
        try:
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Inventory document is not valid UTF-8 JSON") from exc
    else:
        data = raw
    if not isinstance(data, dict):
        raise ValueError("Inventory document must be a JSON object")
    if data.get("version") == 2 and "format" not in data:
        data = normalize_legacy_v2(data)
    try:
        document = PortableInventory.model_validate(data)
    except ValidationError as exc:
        raise ValueError("Inventory document has an unsupported format or version") from exc
    total = _validate_records(document.entities, ENTITY_FIELDS)
    total += _validate_records(document.relationships, RELATIONSHIP_FIELDS)
    if total > MAX_RECORDS:
        raise ValueError(f"Inventory document exceeds the {MAX_RECORDS} record limit")
    return document
