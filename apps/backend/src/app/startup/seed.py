"""First-run content seeding.

Only ever runs against a database that has neither users nor docs, so it cannot
overwrite anything an operator has written.  The seed file itself is resolved
through ``startup.paths`` because packaging puts it in four different places.
"""

import logging

from sqlalchemy.orm import Session

from app.startup.paths import docs_seed_candidates, resolve_existing_path

_logger = logging.getLogger(__name__)


def seed_default_docs(db: Session) -> None:
    """Seed the single shipped default doc on fresh installs.

    Creates one doc from repository root DocsPage.md only when the docs table is empty.
    """
    from app.core.markdown_render import render_markdown
    from app.db.models import Doc, User

    has_users = db.query(User.id).limit(1).first()
    if has_users:
        return

    has_docs = db.query(Doc.id).limit(1).first()
    if has_docs:
        return

    docs_page_path = resolve_existing_path(*docs_seed_candidates())
    if docs_page_path is None:
        _logger.warning("Default docs seed file not found in configured resource paths")
        return
    body_md = docs_page_path.read_text(encoding="utf-8").strip()
    if not body_md:
        _logger.warning("Default docs seed file is empty: %s", docs_page_path)
        return

    title = "Welcome to Circuit Breaker"
    first_line = body_md.splitlines()[0].strip()
    if first_line.startswith("#"):
        parsed_title = first_line.lstrip("#").strip()
        if parsed_title:
            title = parsed_title

    db.add(
        Doc(
            title=title,
            body_md=body_md,
            body_html=render_markdown(body_md),
            category="Getting Started",
            pinned=True,
            icon="book-open",
        )
    )
    db.commit()
