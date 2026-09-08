from datetime import UTC, datetime

import pytest

from app.core.errors import ConflictError
from app.db.models import Hardware, HardwareConnection
from app.schemas.inventory_transfer import PortableInventory, PortableManifest
from app.services.inventory_transfer.apply import apply_import
from app.services.inventory_transfer.export import export_inventory
from app.services.inventory_transfer.format import parse_inventory_document
from app.services.inventory_transfer.plan import build_import_plan, save_preview


def _document(*, hardware=None, relationships=None):
    return PortableInventory(
        format="circuitbreaker.inventory",
        version=1,
        exported_at=datetime.now(UTC),
        manifest=PortableManifest(included=[], excluded=[]),
        entities={"hardware": hardware or []},
        relationships=relationships or {},
    )


def test_export_declares_exclusions_and_includes_hardware_connections(db_session, factories):
    first = factories.hardware(name="first")
    second = factories.hardware(name="second")
    db_session.add(
        HardwareConnection(
            source_hardware_id=first.id,
            target_hardware_id=second.id,
            connection_type="ethernet",
            source="manual",
        )
    )
    db_session.flush()

    exported = export_inventory(db_session)

    assert exported.format == "circuitbreaker.inventory"
    assert "credentials" in exported.manifest.excluded
    assert exported.relationships["hardware_connections"][0]["source_hardware_id"] == first.id


def test_foreign_primary_key_collision_creates_a_new_local_row(db_session, factories):
    actor = factories.user(role="admin")
    existing = factories.hardware(name="existing")
    document = _document(hardware=[{"id": existing.id, "name": "imported"}])
    built = build_import_plan(db_session, document, [])
    preview = save_preview(db_session, document, built, actor_id=actor.id)
    db_session.flush()

    result = apply_import(
        db_session,
        preview.plan_id,
        preview.plan_digest,
        "transfer-retry-key",
        actor_id=actor.id,
    )

    assert result.created["hardware"] == 1
    assert db_session.get(Hardware, existing.id).name == "existing"
    assert db_session.query(Hardware).filter(Hardware.name == "imported").one().id != existing.id


def test_relationship_ids_are_remapped_and_apply_is_replay_safe(db_session, factories):
    actor = factories.user(role="admin")
    document = _document(
        hardware=[{"id": 100, "name": "one"}, {"id": 200, "name": "two"}],
        relationships={
            "hardware_connections": [
                {
                    "source_hardware_id": 100,
                    "target_hardware_id": 200,
                    "connection_type": "ethernet",
                    "source": "manual",
                }
            ]
        },
    )
    built = build_import_plan(db_session, document, [])
    preview = save_preview(db_session, document, built, actor_id=actor.id)
    first = apply_import(
        db_session,
        preview.plan_id,
        preview.plan_digest,
        "same-transfer-key",
        actor_id=actor.id,
    )
    db_session.flush()
    replay = apply_import(
        db_session,
        preview.plan_id,
        preview.plan_digest,
        "same-transfer-key",
        actor_id=actor.id,
    )

    link = db_session.query(HardwareConnection).one()
    assert link.source_hardware_id != 100
    assert link.target_hardware_id != 200
    assert replay.operation_id == first.operation_id
    assert db_session.query(Hardware).count() == 2


def test_missing_reference_blocks_apply_during_preview(db_session, factories):
    actor = factories.user(role="admin")
    document = _document(
        hardware=[{"id": 100, "name": "one"}],
        relationships={
            "hardware_connections": [{"source_hardware_id": 100, "target_hardware_id": 999}]
        },
    )
    built = build_import_plan(db_session, document, [])
    preview = save_preview(db_session, document, built, actor_id=actor.id)

    assert preview.can_apply is False
    assert preview.conflicts[0].reason_code == "missing_reference"
    with pytest.raises(ConflictError, match="unresolved"):
        apply_import(
            db_session,
            preview.plan_id,
            preview.plan_digest,
            "missing-reference-key",
            actor_id=actor.id,
        )
    assert db_session.query(Hardware).count() == 0


def test_inventory_change_invalidates_preview(db_session, factories):
    actor = factories.user(role="admin")
    document = _document(hardware=[{"id": 1, "name": "imported"}])
    built = build_import_plan(db_session, document, [])
    preview = save_preview(db_session, document, built, actor_id=actor.id)
    factories.hardware(name="changed-after-preview")

    with pytest.raises(ConflictError) as caught:
        apply_import(
            db_session,
            preview.plan_id,
            preview.plan_digest,
            "stale-preview-key",
            actor_id=actor.id,
        )
    assert caught.value.error_code == "preview_stale"


def test_parser_rejects_unknown_fields_before_any_orm_work():
    with pytest.raises(ValueError, match="Unsupported fields"):
        parse_inventory_document(
            {
                "format": "circuitbreaker.inventory",
                "version": 1,
                "exported_at": datetime.now(UTC).isoformat(),
                "manifest": {"included": [], "excluded": []},
                "entities": {"hardware": [{"id": 1, "name": "host", "hashed_password": "no"}]},
                "relationships": {},
            }
        )
