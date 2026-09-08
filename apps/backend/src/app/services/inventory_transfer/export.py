"""Explicit portable inventory projection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db import models
from app.schemas.inventory_transfer import PortableInventory, PortableManifest
from app.services.inventory_transfer.format import ENTITY_FIELDS, RELATIONSHIP_FIELDS

_ENTITY_MODELS: dict[str, Any] = {
    "hardware": models.Hardware,
    "compute_units": models.ComputeUnit,
    "services": models.Service,
    "storage": models.Storage,
    "networks": models.Network,
    "misc_items": models.MiscItem,
    "docs": models.Doc,
    "tags": models.Tag,
    "hardware_clusters": models.HardwareCluster,
    "external_nodes": models.ExternalNode,
}

_RELATION_MODELS: dict[str, Any] = {
    "entity_tags": models.EntityTag,
    "entity_docs": models.EntityDoc,
    "service_dependencies": models.ServiceDependency,
    "service_storage": models.ServiceStorage,
    "service_misc": models.ServiceMisc,
    "hardware_networks": models.HardwareNetwork,
    "compute_networks": models.ComputeNetwork,
    "hardware_connections": models.HardwareConnection,
    "hardware_cluster_members": models.HardwareClusterMember,
    "external_node_networks": models.ExternalNodeNetwork,
    "service_external_nodes": models.ServiceExternalNode,
}


def _project(row: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: getattr(row, field) for field in fields}


def export_inventory(db: Session) -> PortableInventory:
    entities = {
        name: [_project(row, ENTITY_FIELDS[name]) for row in db.query(model).order_by(model.id)]
        for name, model in _ENTITY_MODELS.items()
    }
    relationships = {
        name: [
            _project(row, RELATIONSHIP_FIELDS[name]) for row in db.query(model).order_by(model.id)
        ]
        for name, model in _RELATION_MODELS.items()
    }
    return PortableInventory(
        format="circuitbreaker.inventory",
        version=1,
        exported_at=datetime.now(UTC),
        manifest=PortableManifest(
            included=list(ENTITY_FIELDS) + list(RELATIONSHIP_FIELDS),
            excluded=[
                "users",
                "sessions",
                "tokens",
                "credentials",
                "settings",
                "audit_logs",
                "operational_runs",
                "telemetry",
                "map_layouts",
                "uploaded_files",
            ],
        ),
        entities=entities,
        relationships=relationships,
    )
