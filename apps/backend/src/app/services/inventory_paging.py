"""Shared helpers for bounded inventory list pages."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.schemas.inventory import PageRequest, PageResult


def escape_ilike(term: str) -> str:
    """Escape LIKE wildcards for a user-supplied search term."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def paginate_rows(
    db: Session,
    *,
    filtered: Select[Any],
    page: PageRequest,
    sort_columns: dict[str, Any],
    id_column: Any,
) -> tuple[list[Any], int]:
    """Apply stable sort + limit/offset and return (rows, total)."""
    sort_column = sort_columns.get(page.sort)
    if sort_column is None:
        raise ValueError(f"Unsupported sort field: {page.sort}")

    total = db.scalar(select(func.count()).select_from(filtered.order_by(None).subquery())) or 0
    primary_order = sort_column.asc() if page.direction == "asc" else sort_column.desc()
    order_by: list[Any] = [primary_order.nullslast()]
    if page.sort != "id":
        order_by.append(id_column.asc() if page.direction == "asc" else id_column.desc())

    statement = filtered.order_by(*order_by).offset(page.offset).limit(page.limit)
    rows = list(db.execute(statement).unique().scalars().all())
    return rows, int(total)


def page_result(
    items: list[Any],
    *,
    total: int,
    page: PageRequest,
) -> PageResult[Any]:
    """Build the shared PageResult envelope."""
    return PageResult(
        items=items,
        total=total,
        limit=page.limit,
        offset=page.offset,
        sort=page.sort,
        direction=page.direction,
    )
