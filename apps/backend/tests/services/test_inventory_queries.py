"""Canonical inventory identity and selector behavior."""

from app.schemas.inventory import EntityRef
from app.services.inventory_queries import (
    FULL_INVENTORY_ACCESS,
    InventoryAccess,
    list_entity_options,
    normalize_entity_type,
)


def test_entity_aliases_normalize_without_changing_stored_names():
    assert normalize_entity_type("compute") == "compute_unit"
    assert normalize_entity_type("misc") == "misc_item"
    assert normalize_entity_type("external") == "external_node"


def test_selector_retains_selected_labels_and_marks_missing_values(db_session, factories):
    hardware = factories.hardware(name="Alpha host")
    selected = [
        EntityRef(entity_type="hardware", entity_id=hardware.id),
        EntityRef(entity_type="hardware", entity_id=999_999),
    ]

    result = list_entity_options(
        db_session,
        ["hardware"],
        "does-not-match",
        selected,
        "view",
        FULL_INVENTORY_ACCESS,
        10,
    )

    assert result.items == []
    assert result.selected[0].label == "Alpha host"
    assert result.selected[0].available is True
    assert result.selected[1].available is False
    assert result.selected[1].unavailable_reason == "not_found"


def test_selector_does_not_resolve_types_outside_access(db_session, factories):
    hardware = factories.hardware(name="Hidden host")
    ref = EntityRef(entity_type="hardware", entity_id=hardware.id)

    result = list_entity_options(
        db_session,
        ["hardware"],
        None,
        [ref],
        "view",
        InventoryAccess(readable_types=frozenset()),
        10,
    )

    assert result.items == []
    assert result.selected[0].available is False
    assert result.selected[0].unavailable_reason == "unavailable"
    assert "Hidden host" not in result.selected[0].label


def test_selector_rejects_type_not_eligible_for_action(db_session):
    try:
        list_entity_options(
            db_session,
            ["service"],
            None,
            [],
            "docker_parent",
            FULL_INVENTORY_ACCESS,
            10,
        )
    except ValueError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("ineligible selector type was accepted")
