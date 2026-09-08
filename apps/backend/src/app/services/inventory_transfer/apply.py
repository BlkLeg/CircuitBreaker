"""Atomic application and idempotent replay of a confirmed transfer preview."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.time import utcnow
from app.db import models
from app.schemas.inventory_transfer import PortableInventory, TransferApplyResult
from app.services.inventory_transfer.export import _ENTITY_MODELS, _RELATION_MODELS
from app.services.inventory_transfer.format import ENTITY_FIELDS, RELATIONSHIP_FIELDS
from app.services.inventory_transfer.plan import inventory_fingerprint

_ENTITY_ORDER = (
    "tags",
    "docs",
    "hardware",
    "networks",
    "misc_items",
    "hardware_clusters",
    "external_nodes",
    "compute_units",
    "storage",
    "services",
)
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
    "hardware_connections": {"source_hardware_id": "hardware", "target_hardware_id": "hardware"},
    "hardware_cluster_members": {"cluster_id": "hardware_clusters", "hardware_id": "hardware"},
    "external_node_networks": {"external_node_id": "external_nodes", "network_id": "networks"},
    "service_external_nodes": {"service_id": "services", "external_node_id": "external_nodes"},
}
_ATTACHMENT_TYPE = {
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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _remap(value: Any, entity_type: str, mapping: dict[str, dict[int, int]]) -> int | None:
    if value is None:
        return None
    target = mapping.get(entity_type, {}).get(int(value))
    if target is None:
        raise ValidationError("The transfer contains a relationship to a missing source entity.")
    return target


def apply_import(
    db: Session,
    plan_id: str,
    expected_digest: str,
    idempotency_key: str,
    *,
    actor_id: int,
) -> TransferApplyResult:
    request_digest = hashlib.sha256(f"{plan_id}:{expected_digest}".encode()).hexdigest()
    replay = (
        db.query(models.InventoryTransferOperation)
        .filter(
            models.InventoryTransferOperation.actor_id == actor_id,
            models.InventoryTransferOperation.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    if replay is not None:
        if replay.request_digest != request_digest:
            raise ConflictError(
                "This idempotency key was already used for another transfer.",
                error_code="idempotency_conflict",
            )
        if replay.state == "completed" and replay.result_json:
            return TransferApplyResult.model_validate(replay.result_json)
        raise ConflictError("This transfer is already being applied.", error_code="transfer_busy")

    preview = (
        db.query(models.InventoryTransferPlan)
        .filter(models.InventoryTransferPlan.id == plan_id)
        .with_for_update()
        .one_or_none()
    )
    if preview is None or preview.actor_id != actor_id:
        raise NotFoundError("Transfer preview not found.")
    if preview.plan_digest != expected_digest:
        raise ConflictError(
            "The confirmed preview digest does not match.", error_code="preview_changed"
        )
    if _aware(preview.expires_at) <= utcnow():
        preview.status = "expired"
        raise ConflictError(
            "The transfer preview expired; preview it again.", error_code="preview_expired"
        )
    if preview.status == "completed" and preview.result_json:
        return TransferApplyResult.model_validate(preview.result_json)
    if preview.status != "previewed":
        raise ConflictError(
            "The transfer preview is not available to apply.", error_code="transfer_busy"
        )
    if inventory_fingerprint(db) != preview.inventory_digest:
        raise ConflictError(
            "Inventory changed after this preview; review the transfer again.",
            error_code="preview_stale",
        )

    operation = models.InventoryTransferOperation(
        id=uuid4().hex,
        plan_id=preview.id,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        state="applying",
    )
    db.add(operation)
    preview.status = "applying"
    document = PortableInventory.model_validate(preview.document_json)
    if int(preview.plan_json.get("conflict_count", 0)):
        raise ConflictError(
            "The transfer has unresolved conflicts.", error_code="unresolved_transfer"
        )
    actions = {
        name: {int(item["source_id"]): item for item in items}
        for name, items in preview.plan_json["mappings"].items()
    }
    mapping: dict[str, dict[int, int]] = {name: {} for name in ENTITY_FIELDS}
    created: dict[str, int] = {name: 0 for name in ENTITY_FIELDS}
    matched: dict[str, int] = {name: 0 for name in ENTITY_FIELDS}

    for entity_type in _ENTITY_ORDER:
        model: Any = _ENTITY_MODELS[entity_type]
        refs = _INTERNAL_REFS.get(entity_type, {})
        for source in document.entities.get(entity_type, []):
            source_id = int(source["id"])
            action = actions[entity_type].get(source_id)
            if action is None:
                raise ConflictError(
                    "The transfer has unresolved conflicts.", error_code="unresolved_transfer"
                )
            if action["action"] == "match":
                mapping[entity_type][source_id] = int(action["target_id"])
                matched[entity_type] += 1
                continue
            values = {key: value for key, value in source.items() if key != "id"}
            for field, target_type in refs.items():
                if field in values:
                    values[field] = _remap(values[field], target_type, mapping)
            row = model(**values)
            db.add(row)
            db.flush()
            mapping[entity_type][source_id] = row.id
            created[entity_type] += 1

    relationships_created: dict[str, int] = {}
    for relation_type, rows in document.relationships.items():
        model = _RELATION_MODELS[relation_type]
        count = 0
        for source in rows:
            values = dict(source)
            if relation_type in {"entity_tags", "entity_docs"}:
                source_type = _ATTACHMENT_TYPE.get(str(values["entity_type"]))
                if source_type is None:
                    raise ValidationError("An attachment uses an unsupported entity type.")
                values["entity_id"] = _remap(values["entity_id"], source_type, mapping)
                target_field = "tag_id" if relation_type == "entity_tags" else "doc_id"
                target_type = "tags" if relation_type == "entity_tags" else "docs"
                values[target_field] = _remap(values[target_field], target_type, mapping)
            else:
                for field, target_type in _RELATION_REFS[relation_type].items():
                    values[field] = _remap(values.get(field), target_type, mapping)
            db.add(model(**{key: values.get(key) for key in RELATIONSHIP_FIELDS[relation_type]}))
            count += 1
        relationships_created[relation_type] = count
    db.flush()
    result = TransferApplyResult(
        operation_id=operation.id,
        state="completed",
        created=created,
        matched=matched,
        relationships_created=relationships_created,
        warnings=["Operational history, credentials, telemetry, and layouts were not imported."],
    )
    operation.state = "completed"
    operation.result_json = result.model_dump(mode="json")
    operation.completed_at = utcnow()
    preview.status = "completed"
    preview.result_json = result.model_dump(mode="json")
    preview.applied_at = utcnow()
    db.flush()
    return result
