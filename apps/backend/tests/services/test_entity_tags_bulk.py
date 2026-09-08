"""Bulk attachment reads used by bounded inventory serializers."""

from app.db.models import Doc, EntityDoc, EntityTag, Tag
from app.services.entity_tags import get_documents_for_many, get_tags_for_many


def test_bulk_attachment_reads_include_empty_ids_and_exclude_document_bodies(db_session):
    first = 101
    empty = 202
    alpha = Tag(name="alpha")
    zulu = Tag(name="zulu")
    doc = Doc(title="Runbook", body_md="private body", category="ops", icon="book")
    db_session.add_all([alpha, zulu, doc])
    db_session.flush()
    db_session.add_all(
        [
            EntityTag(entity_type="hardware", entity_id=first, tag_id=zulu.id),
            EntityTag(entity_type="hardware", entity_id=first, tag_id=alpha.id),
            EntityDoc(entity_type="hardware", entity_id=first, doc_id=doc.id),
        ]
    )
    db_session.flush()

    tags = get_tags_for_many(db_session, "hardware", [first, empty, first])
    documents = get_documents_for_many(db_session, "hardware", [first, empty])

    assert tags == {first: ["alpha", "zulu"], empty: []}
    assert documents[empty] == []
    assert documents[first] == [
        {"id": doc.id, "title": "Runbook", "category": "ops", "icon": "book"}
    ]
    assert "body_md" not in documents[first][0]


def test_bulk_attachment_reads_reject_unbounded_inputs(db_session):
    entity_ids = list(range(1001))

    try:
        get_tags_for_many(db_session, "hardware", entity_ids)
    except ValueError as exc:
        assert "At most 1000" in str(exc)
    else:
        raise AssertionError("unbounded attachment read was accepted")
