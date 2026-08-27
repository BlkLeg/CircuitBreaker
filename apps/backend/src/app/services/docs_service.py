import io
import re
import zipfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.markdown_render import render_markdown
from app.core.time import utcnow
from app.db.models import Doc, EntityDoc
from app.schemas.docs import DocCreate, DocUpdate, EntityDocAttach

# ── The docs archive budget ──────────────────────────────────────────────────
#
# These four numbers are the *contract between the importer and the exporter*,
# which is why they live in the service layer that both ends reach rather than
# beside either one of them. api/docs.py reaches them through the module
# (`docs_service.MAX_IMPORT_ZIP_BYTES`, never `from ... import`) so that at
# runtime there is exactly one object holding each ceiling: move the number
# here and both ends move with it in the same interpreter, which is the
# property tests/api/test_docs_import_export_limits.py pins by moving one of
# them and watching both ends follow. api/docs.py must not restate any of them
# as a literal. Two copies that happen to agree is how R10 happened: B05
# tightened the import side and left export_docs_zip untouched, so an install
# with more than 500 docs produced an archive its own importer answered with
# 413 — a backup that only turns out to be unrestorable at restore time.
#
# Raising any of these raises the ceiling on what a hostile upload can make the
# API process allocate (see B05: a 10 MB deflate bomb peaked at 142 MB before
# these existed). Lowering any of them makes some existing install's export
# un-reimportable. Either way, both ends move together because there is only
# one definition to move.
MAX_IMPORT_MD_BYTES = 1 * 1024 * 1024  # 1 MB per .md entry
MAX_IMPORT_ZIP_BYTES = 10 * 1024 * 1024  # 10 MB of compressed archive
MAX_IMPORT_ZIP_ENTRIES = 500  # members per archive
MAX_IMPORT_TOTAL_MD_BYTES = 20 * 1024 * 1024  # 20 MB uncompressed across all members

# Name of the member export_docs_zip adds to an archive that the importer would
# refuse. `.md` is the only extension _parse_zip_entries reads, so a `.txt`
# member is skipped on re-import and can never become a doc.
IMPORT_WARNING_MEMBER = "IMPORT-WARNING.txt"


def _slugify(title: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_") or "doc"


def _to_dict(doc: Doc) -> dict:
    return {c.name: getattr(doc, c.name) for c in doc.__table__.columns}


def list_docs(db: Session, *, q: str | None = None) -> list[dict]:
    stmt = select(Doc)
    if q:
        stmt = stmt.where(Doc.title.ilike(f"%{q}%"))
    # Pinned docs always float to the top; within each group sort by recency
    stmt = stmt.order_by(Doc.pinned.desc(), Doc.updated_at.desc())
    rows = db.execute(stmt).scalars().all()
    return [_to_dict(r) for r in rows]


def get_doc(db: Session, doc_id: int) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    return _to_dict(doc)


def create_doc(db: Session, payload: DocCreate) -> dict:
    doc = Doc(
        title=payload.title,
        body_md=payload.body_md,
        body_html=render_markdown(payload.body_md),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_dict(doc)


def update_doc(db: Session, doc_id: int, payload: DocUpdate) -> dict:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(doc, field, value)
    # Re-render HTML when body changes
    if "body_md" in data:
        doc.body_html = render_markdown(doc.body_md)
    doc.updated_at = utcnow()
    db.commit()
    db.refresh(doc)
    return _to_dict(doc)


def delete_doc(db: Session, doc_id: int) -> None:
    doc = db.get(Doc, doc_id)
    if doc is None:
        raise ValueError(f"Doc {doc_id} not found")
    db.delete(doc)
    db.commit()


def attach_doc(db: Session, payload: EntityDocAttach) -> None:
    if db.get(Doc, payload.doc_id) is None:
        raise ValueError(f"Doc {payload.doc_id} not found")
    link = EntityDoc(
        entity_type=payload.entity_type, entity_id=payload.entity_id, doc_id=payload.doc_id
    )
    db.add(link)
    db.commit()


def detach_doc(db: Session, payload: EntityDocAttach) -> None:
    link = db.execute(
        select(EntityDoc).where(
            EntityDoc.entity_type == payload.entity_type,
            EntityDoc.entity_id == payload.entity_id,
            EntityDoc.doc_id == payload.doc_id,
        )
    ).scalar_one_or_none()
    if link is None:
        raise ValueError("Doc attachment not found")
    db.delete(link)
    db.commit()


def docs_by_entity(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    links = (
        db.execute(
            select(EntityDoc).where(
                EntityDoc.entity_type == entity_type,
                EntityDoc.entity_id == entity_id,
            )
        )
        .scalars()
        .all()
    )
    result = []
    for link in links:
        doc = db.get(Doc, link.doc_id)
        if doc:
            result.append(_to_dict(doc))
    return result


def export_docs_zip(db: Session, ids: list[int] | None = None) -> bytes:
    """Return an in-memory ZIP archive containing one .md file per doc.

    The four ceilings this measures against are the *same objects* api/docs.py
    measures an upload against (see the block at the top of this module), so
    the two ends of the docs archive cannot drift apart the way R10 describes:
    there is one definition, read at call time by both.

    What this deliberately does NOT do is refuse to build an over-ceiling
    archive. An earlier pass at R10 raised on one, and that took docs export
    away from precisely the installs R10 is about: the only caller in the
    product is `docsApi.exportAll()` (apps/frontend/src/api/client.jsx), which
    passes no `ids` and has no subset-export UI behind it, and it asks for the
    response as a Blob — so a 413's JSON `detail` is never parsed and the
    operator's toast reads "Request failed with status code 413" no matter how
    carefully the detail is worded. A large install was left with no way at all
    to get its docs out, in exchange for a warning it could not read. The .md
    files in an over-ceiling archive are perfectly good markdown that any unzip
    tool opens; only feeding the whole archive back to POST /docs/import in one
    piece is refused.

    So the archive is always produced, and an over-ceiling one carries
    IMPORT_WARNING_MEMBER naming every ceiling it breaks. That puts the warning
    in the artifact the operator still has at restore time, which is the moment
    R10 is actually about. The residual — an archive this endpoint produced can
    still be one this API's own importer refuses — stays open, and closing it
    needs a chunked export plus a subset-export UI on the frontend, not a
    refusal here.
    """
    stmt = select(Doc)
    if ids:
        stmt = stmt.where(Doc.id.in_(ids))
    docs = db.execute(stmt).scalars().all()

    breaches: list[str] = []
    if len(docs) > MAX_IMPORT_ZIP_ENTRIES:
        breaches.append(
            f"the archive holds {len(docs)} members, over the "
            f"{MAX_IMPORT_ZIP_ENTRIES}-member import ceiling"
        )

    total_md_bytes = 0
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            # Encode once and measure the encoded bytes. len() of the encoded
            # body is exactly the ZipInfo.file_size the importer weighs against
            # MAX_IMPORT_MD_BYTES; len(doc.body_md) would count *characters*,
            # and a single multi-byte character is enough to make the two ends
            # disagree about the same doc — the same class of drift R10 is,
            # one layer down. The name is built once here too, so the warning
            # below names the member the operator will actually see.
            # body_md is NOT NULL in the schema; the `or ""` is belt and braces
            # for a row that predates that and would otherwise raise here.
            filename = f"{doc.id}-{_slugify(doc.title)}.md"
            body = (doc.body_md or "").encode("utf-8")
            if len(body) > MAX_IMPORT_MD_BYTES:
                breaches.append(
                    f"{filename} is {len(body)} bytes, over the "
                    f"{MAX_IMPORT_MD_BYTES}-byte per-member import ceiling"
                )
            total_md_bytes += len(body)
            # Written straight through rather than collected into a list first:
            # holding a second full copy of every body alongside the ORM rows
            # and the ZIP buffer doubles peak memory on the largest export for
            # no gain.
            zf.writestr(filename, body)

    if total_md_bytes > MAX_IMPORT_TOTAL_MD_BYTES:
        breaches.append(
            f"the members total {total_md_bytes} uncompressed bytes, over the "
            f"{MAX_IMPORT_TOTAL_MD_BYTES}-byte import ceiling"
        )
    data = buf.getvalue()
    if len(data) > MAX_IMPORT_ZIP_BYTES:
        breaches.append(
            f"the archive is {len(data)} compressed bytes, over the "
            f"{MAX_IMPORT_ZIP_BYTES}-byte import ceiling"
        )

    if not breaches:
        return data

    # Only ever appended to an archive that already breaks a ceiling. An
    # in-ceiling export must come back byte-identical to what it always was:
    # an archive sitting exactly on the 500-member cap would be pushed over it
    # by an unconditional extra member, i.e. the warning would itself become
    # the thing that made a good backup unimportable.
    with zipfile.ZipFile(buf, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(IMPORT_WARNING_MEMBER, _import_warning(breaches))
    return buf.getvalue()


def _import_warning(breaches: list[str]) -> str:
    lines = "\n".join(f"  - {b}" for b in breaches)
    return (
        "This archive cannot be restored through POST /api/v1/docs/import in one\n"
        "piece. That endpoint refuses it with 413 because:\n\n"
        f"{lines}\n\n"
        "The .md files in here are complete and readable with any unzip tool; it\n"
        "is only the single-shot re-import that is refused. To restore it, take\n"
        "the export in several smaller archives: GET /api/v1/docs/export accepts\n"
        "?ids=1&ids=2 and exports just those docs.\n"
    )


def import_docs(db: Session, entries: list[tuple[str, str]]) -> list[dict]:
    """Create docs from a list of (title, body_md) tuples; returns the created doc dicts."""
    created = []
    for title, body_md in entries:
        doc = create_doc(db, DocCreate(title=title, body_md=body_md))
        created.append(doc)
    return created


def entities_by_doc(db: Session, doc_id: int) -> list[dict]:
    """Return all entity links for a given doc (reverse lookup for backlinks panel)."""
    if db.get(Doc, doc_id) is None:
        raise ValueError(f"Doc {doc_id} not found")
    links = db.execute(select(EntityDoc).where(EntityDoc.doc_id == doc_id)).scalars().all()
    return [{"entity_type": link.entity_type, "entity_id": link.entity_id} for link in links]
