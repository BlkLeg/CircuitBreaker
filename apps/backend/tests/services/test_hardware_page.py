"""Bounded Hardware inventory page service."""

from sqlalchemy import event

from app.schemas.inventory import PageRequest
from app.services.entity_tags import sync_tags
from app.services.hardware_service import list_hardware_page


def test_hardware_page_filters_before_paging_and_uses_stable_sort(db_session, factories):
    first = factories.hardware(name="Same", role="server")
    second = factories.hardware(name="Same", role="server")
    factories.hardware(name="Other", role="router")
    sync_tags(db_session, "hardware", first.id, ["selected"])
    sync_tags(db_session, "hardware", second.id, ["selected"])

    result = list_hardware_page(
        db_session,
        PageRequest(limit=1, offset=1, sort="name", direction="asc"),
        tag="selected",
        role="server",
    )

    assert result.total == 2
    assert [item["id"] for item in result.items] == [second.id]
    assert result.items[0]["tags"] == ["selected"]


def test_hardware_page_query_count_does_not_grow_per_item(db_session, factories):
    for index in range(8):
        factories.hardware(name=f"Bounded {index}")
    statements: list[str] = []

    def record_statement(*args):
        statements.append(args[2])

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = list_hardware_page(
            db_session,
            PageRequest(limit=8, sort="name", direction="asc"),
            q="Bounded",
        )
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert len(result.items) == 8
    assert len(statements) <= 6
