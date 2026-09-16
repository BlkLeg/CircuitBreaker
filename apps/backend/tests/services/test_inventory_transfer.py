from datetime import UTC, datetime

import pytest

from app.core.errors import ConflictError, NotFoundError
from app.db.models import (
    EntityTag,
    Hardware,
    HardwareConnection,
    InventoryTransferOperation,
    Service,
    ServiceDependency,
    Tag,
)
from app.schemas.inventory_transfer import (
    PortableInventory,
    PortableManifest,
    TransferResolution,
)
from app.services.inventory_transfer.apply import apply_import, completed_operation_result
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


def _completed_operation(db_session, factories, actor):
    """One applied transfer, so its result can be fetched back afterwards."""
    document = _document(hardware=[{"id": 100, "name": "one"}])
    built = build_import_plan(db_session, document, [])
    preview = save_preview(db_session, document, built, actor_id=actor.id)
    applied = apply_import(
        db_session,
        preview.plan_id,
        preview.plan_digest,
        "fetch-result-key",
        actor_id=actor.id,
    )
    db_session.flush()
    return applied


def test_completed_operation_result_is_readable_by_its_own_actor(db_session, factories):
    """The result route asks a service for this rather than querying in the route.

    It is the same lookup `apply_import` already performs for replay
    detection — actor-scoped, `state == "completed"`, result JSON present —
    and it belongs beside it: routes stay thin (CLAUDE.md), and
    `tests/build`'s api-boundary ratchet is the gate that says so.
    """
    actor = factories.user(role="admin")
    applied = _completed_operation(db_session, factories, actor)

    fetched = completed_operation_result(db_session, applied.operation_id, actor_id=actor.id)

    assert fetched.operation_id == applied.operation_id
    assert fetched == applied


def test_completed_operation_result_is_not_readable_by_another_actor(db_session, factories):
    """Actor scoping is authorization, not a filter for convenience: a transfer
    result names what an admin imported and what it collided with."""
    actor = factories.user(role="admin")
    other = factories.user(role="admin")
    applied = _completed_operation(db_session, factories, actor)

    with pytest.raises(NotFoundError):
        completed_operation_result(db_session, applied.operation_id, actor_id=other.id)


def test_completed_operation_result_rejects_an_unknown_operation(db_session, factories):
    actor = factories.user(role="admin")

    with pytest.raises(NotFoundError):
        completed_operation_result(db_session, "does-not-exist", actor_id=actor.id)


def test_completed_operation_result_refuses_an_operation_still_running(db_session, factories):
    """A row exists from the moment the apply starts. Returning its empty result
    would report a transfer that has not happened as one that has."""
    actor = factories.user(role="admin")
    applied = _completed_operation(db_session, factories, actor)
    row = db_session.get(InventoryTransferOperation, applied.operation_id)
    row.state = "running"
    row.result_json = None
    db_session.flush()

    with pytest.raises(NotFoundError):
        completed_operation_result(db_session, applied.operation_id, actor_id=actor.id)


# ── Resolution vocabulary: rename, reassign, and their honest limits ─────────


def _doc(entities, relationships=None):
    return PortableInventory(
        format="circuitbreaker.inventory",
        version=1,
        exported_at=datetime.now(UTC),
        manifest=PortableManifest(included=[], excluded=[]),
        entities=entities,
        relationships=relationships or {},
    )


def _preview(db_session, document, resolutions, *, actor):
    built = build_import_plan(db_session, document, resolutions)
    return save_preview(db_session, document, built, actor_id=actor.id)


def test_rename_resolution_creates_a_distinct_row_under_the_new_value(db_session, factories):
    actor = factories.user(role="admin")
    factories.service(name="grafana", slug="grafana")
    document = _doc({"services": [{"id": 7, "name": "grafana", "slug": "grafana"}]})

    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is False
    conflict = preview.conflicts[0]
    assert conflict.reason_code == "unique_identity_conflict"
    assert conflict.field == "slug"
    assert conflict.candidate_labels == ["grafana"]

    resolutions = [
        TransferResolution(
            entity_type="services", source_id=7, action="rename", new_value="grafana-lab"
        )
    ]
    renamed = _preview(db_session, document, resolutions, actor=actor)

    assert renamed.can_apply is True
    result = apply_import(
        db_session,
        renamed.plan_id,
        renamed.plan_digest,
        "rename-transfer-key",
        actor_id=actor.id,
    )
    assert result.created["services"] == 1
    assert sorted(s.slug for s in db_session.query(Service).all()) == ["grafana", "grafana-lab"]


def test_rename_rejects_values_already_claimed(db_session, factories):
    factories.service(name="grafana", slug="grafana")
    factories.service(name="grafana-lab", slug="grafana-lab")
    document = _doc({"services": [{"id": 7, "name": "grafana", "slug": "grafana"}]})

    with pytest.raises(ValueError, match="already used"):
        build_import_plan(
            db_session,
            document,
            [
                TransferResolution(
                    entity_type="services", source_id=7, action="rename", new_value="grafana-lab"
                )
            ],
        )

    both_new = _doc(
        {
            "services": [
                {"id": 7, "name": "one", "slug": "one"},
                {"id": 8, "name": "two", "slug": "two"},
            ]
        }
    )
    with pytest.raises(ValueError, match="both use"):
        build_import_plan(
            db_session,
            both_new,
            [
                TransferResolution(
                    entity_type="services", source_id=7, action="rename", new_value="shared"
                ),
                TransferResolution(
                    entity_type="services", source_id=8, action="rename", new_value="shared"
                ),
            ],
        )


def test_rename_is_rejected_for_records_without_a_unique_identity_field(db_session, factories):
    document = _doc({"hardware": [{"id": 1, "name": "pve-01"}]})
    with pytest.raises(ValueError, match="renamable"):
        build_import_plan(
            db_session,
            document,
            [
                TransferResolution(
                    entity_type="hardware", source_id=1, action="rename", new_value="pve-02"
                )
            ],
        )


def test_duplicate_identity_inside_one_document_is_a_conflict(db_session, factories):
    actor = factories.user(role="admin")
    document = _doc(
        {
            "services": [
                {"id": 7, "name": "one", "slug": "dup"},
                {"id": 8, "name": "two", "slug": "dup"},
            ]
        }
    )

    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is False
    assert preview.conflicts[0].reason_code == "duplicate_source_identity"
    assert preview.conflicts[0].field == "slug"
    with pytest.raises(ConflictError, match="unresolved"):
        apply_import(
            db_session,
            preview.plan_id,
            preview.plan_digest,
            "duplicate-identity-key",
            actor_id=actor.id,
        )
    assert db_session.query(Service).count() == 0


def test_reassign_binds_a_missing_parent_to_an_existing_local_asset(db_session, factories):
    actor = factories.user(role="admin")
    docker01 = factories.hardware(name="docker-01")
    document = _doc(
        {"services": [{"id": 5, "name": "paperless", "slug": "paperless", "hardware_id": 999}]}
    )

    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is False
    assert preview.conflicts[0].reason_code == "missing_reference"
    assert preview.conflicts[0].field == "hardware_id"

    resolutions = [
        TransferResolution(
            entity_type="services",
            source_id=5,
            action="reassign",
            field="hardware_id",
            target_id=docker01.id,
        )
    ]
    reassigned = _preview(db_session, document, resolutions, actor=actor)

    assert reassigned.can_apply is True
    result = apply_import(
        db_session,
        reassigned.plan_id,
        reassigned.plan_digest,
        "reassign-transfer-key",
        actor_id=actor.id,
    )
    assert result.created["services"] == 1
    imported = db_session.query(Service).filter(Service.slug == "paperless").one()
    assert imported.hardware_id == docker01.id


def test_reassign_binds_a_relationship_reference_to_an_existing_local_asset(db_session, factories):
    actor = factories.user(role="admin")
    prometheus = factories.service(name="prometheus", slug="prometheus")
    document = _doc(
        {"services": [{"id": 5, "name": "grafana", "slug": "grafana"}]},
        {
            "service_dependencies": [
                {"service_id": 5, "depends_on_id": 999, "connection_type": "http"}
            ]
        },
    )

    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is False
    conflict = preview.conflicts[0]
    assert conflict.reason_code == "missing_reference"
    assert conflict.entity_type == "service_dependencies"
    assert conflict.field == "depends_on_id"

    resolutions = [
        TransferResolution(
            entity_type="service_dependencies",
            source_id=1,
            action="reassign",
            field="depends_on_id",
            target_id=prometheus.id,
        )
    ]
    reassigned = _preview(db_session, document, resolutions, actor=actor)

    assert reassigned.can_apply is True
    apply_import(
        db_session,
        reassigned.plan_id,
        reassigned.plan_digest,
        "relation-reassign-key",
        actor_id=actor.id,
    )
    dependency = db_session.query(ServiceDependency).one()
    assert dependency.depends_on_id == prometheus.id
    assert dependency.service_id != 5


def test_attachment_reassign_binds_a_tag_to_an_existing_local_asset(db_session, factories):
    actor = factories.user(role="admin")
    tag = Tag(name="core", color="#79740e")
    db_session.add(tag)
    db_session.flush()
    document = _doc(
        {"hardware": [{"id": 1, "name": "new-host"}]},
        {"entity_tags": [{"entity_type": "hardware", "entity_id": 1, "tag_id": 3}]},
    )

    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is False
    assert preview.conflicts[0].reason_code == "missing_reference"
    assert preview.conflicts[0].field == "tag_id"

    resolutions = [
        TransferResolution(
            entity_type="entity_tags",
            source_id=1,
            action="reassign",
            field="tag_id",
            target_id=tag.id,
        )
    ]
    reassigned = _preview(db_session, document, resolutions, actor=actor)
    apply_import(
        db_session,
        reassigned.plan_id,
        reassigned.plan_digest,
        "attachment-reassign-key",
        actor_id=actor.id,
    )
    link = db_session.query(EntityTag).one()
    assert link.tag_id == tag.id
    assert link.entity_id == db_session.query(Hardware).filter(Hardware.name == "new-host").one().id


def test_match_and_reassign_on_one_record_are_contradictory(db_session, factories):
    existing = factories.service(name="grafana", slug="grafana")
    document = _doc(
        {"services": [{"id": 7, "name": "grafana", "slug": "grafana", "hardware_id": 999}]}
    )
    with pytest.raises(ValueError, match="reassigned"):
        build_import_plan(
            db_session,
            document,
            [
                TransferResolution(
                    entity_type="services", source_id=7, action="match", target_id=existing.id
                ),
                TransferResolution(
                    entity_type="services",
                    source_id=7,
                    action="reassign",
                    field="hardware_id",
                    target_id=existing.id,
                ),
            ],
        )


def test_duplicate_resolutions_for_one_record_are_rejected(db_session, factories):
    document = _doc({"services": [{"id": 7, "name": "one", "slug": "one"}]})
    with pytest.raises(ValueError, match="Duplicate"):
        build_import_plan(
            db_session,
            document,
            [
                TransferResolution(
                    entity_type="services", source_id=7, action="rename", new_value="x"
                ),
                TransferResolution(
                    entity_type="services", source_id=7, action="rename", new_value="y"
                ),
            ],
        )


def test_relationship_rows_cannot_be_matched_or_renamed(db_session, factories):
    document = _doc(
        {"hardware": [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}]},
        {
            "hardware_connections": [
                {"source_hardware_id": 1, "target_hardware_id": 2, "connection_type": "ethernet"}
            ]
        },
    )
    with pytest.raises(ValueError, match="cannot be matched"):
        build_import_plan(
            db_session,
            document,
            [
                TransferResolution(
                    entity_type="hardware_connections",
                    source_id=1,
                    action="rename",
                    new_value="renamed",
                )
            ],
        )


def test_legacy_v2_export_previews_and_applies_through_the_portable_contract(db_session, factories):
    actor = factories.user(role="admin")
    legacy = {
        "version": 2,
        "exported_at": datetime.now(UTC).isoformat(),
        "hardware": [{"id": 1, "name": "legacy-host"}],
    }

    document = parse_inventory_document(legacy)
    assert document.version == 1
    preview = _preview(db_session, document, [], actor=actor)

    assert preview.can_apply is True
    result = apply_import(
        db_session,
        preview.plan_id,
        preview.plan_digest,
        "legacy-transfer-key",
        actor_id=actor.id,
    )
    assert result.created["hardware"] == 1
