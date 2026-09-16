"""Bounded inventory page services for sibling entity types."""

from sqlalchemy import event

from app.schemas.inventory import PageRequest
from app.services.compute_units_service import list_compute_units_page
from app.services.entity_tags import sync_tags
from app.services.external_nodes_service import list_external_nodes_page
from app.services.misc_service import list_misc_page
from app.services.services_service import list_services_page
from app.services.storage_service import list_storage_page


def _count_statements(db_session, fn):
    statements: list[str] = []

    def record_statement(*args):
        statements.append(args[2])

    bind = db_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = fn()
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)
    return result, statements


def test_storage_page_query_count_does_not_grow_per_item(db_session, factories):
    for index in range(8):
        row = factories.storage(name=f"Disk {index}")
        sync_tags(db_session, "storage", row.id, ["lab"])

    result, statements = _count_statements(
        db_session,
        lambda: list_storage_page(
            db_session, PageRequest(limit=8, sort="name", direction="asc"), q="Disk", tag="lab"
        ),
    )
    assert len(result.items) == 8
    assert len(statements) <= 5


def test_misc_page_query_count_does_not_grow_per_item(db_session, factories):
    for index in range(8):
        row = factories.misc_item(name=f"Asset {index}")
        sync_tags(db_session, "misc", row.id, ["lab"])

    result, statements = _count_statements(
        db_session,
        lambda: list_misc_page(
            db_session, PageRequest(limit=8, sort="name", direction="asc"), q="Asset", tag="lab"
        ),
    )
    assert len(result.items) == 8
    assert len(statements) <= 5


def test_compute_page_query_count_does_not_grow_per_item(db_session, factories):
    hardware = factories.hardware(name="Host")
    for index in range(8):
        row = factories.compute_unit(name=f"CU {index}", hardware_id=hardware.id)
        sync_tags(db_session, "compute", row.id, ["lab"])

    result, statements = _count_statements(
        db_session,
        lambda: list_compute_units_page(
            db_session, PageRequest(limit=8, sort="name", direction="asc"), q="CU", tag="lab"
        ),
    )
    assert len(result.items) == 8
    assert len(statements) <= 8


def test_services_page_query_count_does_not_grow_per_item(db_session, factories):
    for index in range(8):
        row = factories.service(name=f"Svc {index}")
        sync_tags(db_session, "service", row.id, ["lab"])

    result, statements = _count_statements(
        db_session,
        lambda: list_services_page(
            db_session, PageRequest(limit=8, sort="name", direction="asc"), q="Svc", tag="lab"
        ),
    )
    assert len(result.items) == 8
    assert len(statements) <= 7


def test_external_nodes_page_query_count_does_not_grow_per_item(db_session, factories):
    for index in range(8):
        row = factories.external_node(name=f"Cloud {index}")
        sync_tags(db_session, "external", row.id, ["lab"])

    result, statements = _count_statements(
        db_session,
        lambda: list_external_nodes_page(
            db_session, PageRequest(limit=8, sort="name", direction="asc"), q="Cloud", tag="lab"
        ),
    )
    assert len(result.items) == 8
    assert len(statements) <= 6


def test_sibling_pages_filter_before_paging(db_session, factories):
    first = factories.storage(name="Same", kind="disk")
    second = factories.storage(name="Same", kind="disk")
    factories.storage(name="Other", kind="pool")
    sync_tags(db_session, "storage", first.id, ["selected"])
    sync_tags(db_session, "storage", second.id, ["selected"])

    result = list_storage_page(
        db_session,
        PageRequest(limit=1, offset=1, sort="name", direction="asc"),
        tag="selected",
        kind="disk",
    )
    assert result.total == 2
    assert [item["id"] for item in result.items] == [second.id]
