"""Bounded and deterministic cross-entity search."""

from app.services.inventory_queries import FULL_INVENTORY_ACCESS
from app.services.search_service import search_entities


def test_search_ranks_exact_prefix_and_substring_across_types(db_session, factories):
    factories.hardware(name="needle elsewhere")
    factories.hardware(name="needle host")
    exact_hardware = factories.hardware(name="needle")
    exact_service = factories.service(name="needle", slug="needle-service")

    result = search_entities(db_session, "NeEdLe", FULL_INVENTORY_ACCESS, 3)

    assert [item.entity_id for item in result.items[:2]] == [
        exact_hardware.id,
        exact_service.id,
    ]
    assert [item.entity_type for item in result.items[:2]] == ["hardware", "service"]
    assert result.items[2].title == "needle elsewhere"
    assert result.has_more is True
    assert result.items[0].id == f"hardware-{exact_hardware.id}"


def test_search_treats_sql_wildcards_as_literal_text(db_session, factories):
    literal_match = factories.hardware(name="Load 100%")
    factories.hardware(name="Load ordinary")

    result = search_entities(db_session, "%", FULL_INVENTORY_ACCESS, 20)

    assert [(item.entity_type, item.entity_id) for item in result.items] == [
        ("hardware", literal_match.id)
    ]
