"""Deterministic, mutation-free planning for portable inventory merge."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db import models
from app.schemas.inventory_transfer import (
    PortableInventory,
    TransferConflict,
    TransferPreviewResult,
    TransferResolution,
)
from app.services.inventory_transfer.export import _ENTITY_MODELS

PREVIEW_TTL = timedelta(minutes=30)

_UNIQUE_FIELDS = {
    "services": "slug",
    "tags": "name",
    "hardware_clusters": "name",
}
_INTERNAL_REFS = {
    "compute_units": {"hardware_id": "hardware"},
    "storage": {"hardware_id": "hardware"},
    "services": {"hardware_id": "hardware", "compute_id": "compute_units"},
    "networks": {"gateway_hardware_id": "hardware"},
}
_RELATION_REFS = {
    "service_dependencies": {"service_id": "services", "depends_on_id": "services"},
    "service_storage": {"service_id": "services", "storage_id": "storage"},
    "service_misc": {"service_id": "services", "misc_id": "misc_items"},
    "hardware_networks": {"hardware_id": "hardware", "network_id": "networks"},
    "compute_networks": {"compute_id": "compute_units", "network_id": "networks"},
    "hardware_connections": {
        "source_hardware_id": "hardware",
        "target_hardware_id": "hardware",
    },
    "hardware_cluster_members": {
        "cluster_id": "hardware_clusters",
        "hardware_id": "hardware",
    },
    "external_node_networks": {
        "external_node_id": "external_nodes",
        "network_id": "networks",
    },
    "service_external_nodes": {
        "service_id": "services",
        "external_node_id": "external_nodes",
    },
}
_ATTACHMENT_TYPES = {
    "hardware": "hardware",
    "compute": "compute_units",
    "compute_unit": "compute_units",
    "service": "services",
    "storage": "storage",
    "network": "networks",
    "misc": "misc_items",
    "misc_item": "misc_items",
    "external": "external_nodes",
    "external_node": "external_nodes",
}


@dataclass(frozen=True)
class BuiltImportPlan:
    document_digest: str
    inventory_digest: str
    plan_digest: str
    plan_json: dict[str, Any]
    conflicts: list[TransferConflict]


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def inventory_fingerprint(db: Session) -> str:
    snapshot: dict[str, list[list[Any]]] = {}
    for name, model in _ENTITY_MODELS.items():
        field = _UNIQUE_FIELDS.get(name)
        columns = [model.id]
        if field:
            columns.append(getattr(model, field))
        snapshot[name] = [list(row) for row in db.query(*columns).order_by(model.id).all()]
    return _stable_digest(snapshot)


def build_import_plan(
    db: Session,
    document: PortableInventory,
    resolutions: list[TransferResolution],
) -> BuiltImportPlan:
    resolution_map = {(item.entity_type, item.source_id): item for item in resolutions}
    if len(resolution_map) != len(resolutions):
        raise ValueError("Duplicate conflict resolutions were supplied")
    mappings: dict[str, list[dict[str, Any]]] = {}
    conflicts: list[TransferConflict] = []
    creates: dict[str, int] = {}
    matches: dict[str, int] = {}
    for entity_type, rows in document.entities.items():
        model: Any = _ENTITY_MODELS[entity_type]
        mappings[entity_type] = []
        creates[entity_type] = 0
        matches[entity_type] = 0
        unique_field = _UNIQUE_FIELDS.get(entity_type)
        for row in rows:
            source_id = int(row["id"])
            resolution = resolution_map.get((entity_type, source_id))
            if resolution is not None:
                target = db.get(model, resolution.target_id)
                if target is None:
                    conflicts.append(
                        TransferConflict(
                            entity_type=entity_type,
                            source_id=source_id,
                            reason_code="match_not_found",
                            message="The selected local match no longer exists.",
                        )
                    )
                    continue
                mappings[entity_type].append(
                    {"source_id": source_id, "action": "match", "target_id": target.id}
                )
                matches[entity_type] += 1
                continue
            candidates: list[int] = []
            if unique_field and row.get(unique_field) is not None:
                candidates = [
                    item[0]
                    for item in db.query(model.id)
                    .filter(getattr(model, unique_field) == row[unique_field])
                    .limit(20)
                    .all()
                ]
            if candidates:
                conflicts.append(
                    TransferConflict(
                        entity_type=entity_type,
                        source_id=source_id,
                        reason_code="unique_identity_conflict",
                        message=(
                            f"A local {entity_type} record uses the same {unique_field}; "
                            "choose it explicitly or revise the source inventory."
                        ),
                        candidates=candidates,
                    )
                )
                continue
            mappings[entity_type].append({"source_id": source_id, "action": "create"})
            creates[entity_type] += 1

    source_ids = {
        name: {int(row["id"]) for row in rows} for name, rows in document.entities.items()
    }

    def require_ref(
        owner_type: str, owner_id: int, field: str, target_type: str, value: Any
    ) -> None:
        if value is None:
            return
        if not isinstance(value, int) or value not in source_ids[target_type]:
            conflicts.append(
                TransferConflict(
                    entity_type=owner_type,
                    source_id=owner_id,
                    reason_code="missing_reference",
                    message=f"{field} refers to a source entity that is not in the document.",
                )
            )

    for entity_type, refs in _INTERNAL_REFS.items():
        for source in document.entities.get(entity_type, []):
            for field, target_type in refs.items():
                require_ref(entity_type, int(source["id"]), field, target_type, source.get(field))
    for relation_type, rows in document.relationships.items():
        for index, source in enumerate(rows, start=1):
            if relation_type in {"entity_tags", "entity_docs"}:
                attachment_target_type = _ATTACHMENT_TYPES.get(str(source.get("entity_type")))
                if attachment_target_type is None:
                    conflicts.append(
                        TransferConflict(
                            entity_type=relation_type,
                            source_id=index,
                            reason_code="unsupported_reference_type",
                            message="The attachment entity type is not portable.",
                        )
                    )
                else:
                    require_ref(
                        relation_type,
                        index,
                        "entity_id",
                        attachment_target_type,
                        source.get("entity_id"),
                    )
                field = "tag_id" if relation_type == "entity_tags" else "doc_id"
                target = "tags" if relation_type == "entity_tags" else "docs"
                require_ref(relation_type, index, field, target, source.get(field))
            else:
                for field, target_type in _RELATION_REFS[relation_type].items():
                    require_ref(relation_type, index, field, target_type, source.get(field))

    document_json = document.model_dump(mode="json")
    document_digest = _stable_digest(document_json)
    inventory_digest = inventory_fingerprint(db)
    plan_json = {
        "mappings": mappings,
        "creates": creates,
        "matches": matches,
        "relationships": {name: len(rows) for name, rows in document.relationships.items()},
        "resolutions": [item.model_dump(mode="json") for item in resolutions],
        "conflict_count": len(conflicts),
    }
    plan_digest = _stable_digest(
        {
            "document_digest": document_digest,
            "inventory_digest": inventory_digest,
            "plan": plan_json,
        }
    )
    return BuiltImportPlan(
        document_digest=document_digest,
        inventory_digest=inventory_digest,
        plan_digest=plan_digest,
        plan_json=plan_json,
        conflicts=conflicts,
    )


def save_preview(
    db: Session,
    document: PortableInventory,
    built: BuiltImportPlan,
    *,
    actor_id: int,
) -> TransferPreviewResult:
    expires_at = utcnow() + PREVIEW_TTL
    row = models.InventoryTransferPlan(
        id=uuid4().hex,
        actor_id=actor_id,
        status="previewed",
        document_digest=built.document_digest,
        plan_digest=built.plan_digest,
        inventory_digest=built.inventory_digest,
        document_json=document.model_dump(mode="json"),
        plan_json=built.plan_json,
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return TransferPreviewResult(
        plan_id=row.id,
        plan_digest=row.plan_digest,
        expires_at=expires_at,
        creates=built.plan_json["creates"],
        matches=built.plan_json["matches"],
        relationships=built.plan_json["relationships"],
        conflicts=built.conflicts,
        can_apply=not built.conflicts,
        warnings=[
            "This merge creates new local IDs and does not restore users, secrets, "
            "telemetry, or layouts."
        ],
    )
