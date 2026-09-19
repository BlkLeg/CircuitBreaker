"""Bounded, cross-domain inventory lookup helpers.

These queries deliberately return only picker/search metadata. Rich entity
serialization remains in each domain service so cross-domain callers cannot
accidentally trigger relationship or secret-bearing payloads.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, case, func, literal, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.db.models import ComputeUnit, ExternalNode, Hardware, MiscItem, Network, Service, Storage
from app.schemas.inventory import (
    EntityOption,
    EntityOptionResult,
    EntityRef,
    EntityType,
    SelectionAction,
)

_MAX_RESOLVE_REFS = 100


@dataclass(frozen=True)
class EntityQuerySpec:
    """The finite query metadata for one supported inventory entity type."""

    entity_type: EntityType
    legacy_type: str
    attachment_type: str
    model: type[Any]
    description_attribute: str
    action_url: str


@dataclass(frozen=True)
class InventoryAccess:
    """Entity types the already-authenticated caller may read."""

    readable_types: frozenset[EntityType]


@dataclass(frozen=True)
class EntityQueryPlan:
    """A minimal entity statement and its matching count statement."""

    statement: Select[Any]
    count_statement: Select[Any]


ENTITY_SPECS: dict[EntityType, EntityQuerySpec] = {
    "hardware": EntityQuerySpec("hardware", "hardware", "hardware", Hardware, "notes", "/hardware"),
    "compute_unit": EntityQuerySpec(
        "compute_unit", "compute", "compute", ComputeUnit, "notes", "/compute-units"
    ),
    "service": EntityQuerySpec(
        "service", "service", "service", Service, "description", "/services"
    ),
    "storage": EntityQuerySpec("storage", "storage", "storage", Storage, "notes", "/storage"),
    "network": EntityQuerySpec(
        "network", "network", "network", Network, "description", "/networks"
    ),
    "misc_item": EntityQuerySpec("misc_item", "misc", "misc", MiscItem, "description", "/misc"),
    "external_node": EntityQuerySpec(
        "external_node", "external", "external", ExternalNode, "notes", "/external-nodes"
    ),
}

ENTITY_TYPE_ALIASES: dict[str, EntityType] = {
    **{entity_type: entity_type for entity_type in ENTITY_SPECS},
    "compute": "compute_unit",
    "misc": "misc_item",
    "external": "external_node",
}

FULL_INVENTORY_ACCESS = InventoryAccess(readable_types=frozenset(ENTITY_SPECS))

_ACTION_TYPES: dict[SelectionAction, frozenset[EntityType]] = {
    "view": frozenset(ENTITY_SPECS),
    "relate": frozenset(ENTITY_SPECS),
    "monitor": frozenset({"hardware", "compute_unit", "service", "external_node"}),
    "docker_parent": frozenset({"hardware", "compute_unit"}),
}


def normalize_entity_type(value: str) -> EntityType:
    """Translate an established consumer alias to its canonical entity type."""
    normalized = ENTITY_TYPE_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported entity type: {value}")
    return normalized


def eligible_types(action: SelectionAction) -> frozenset[EntityType]:
    """Return the fixed set of entity types eligible for a selector action."""
    return _ACTION_TYPES[action]


def _require_readable(entity_type: EntityType, access: InventoryAccess) -> EntityQuerySpec:
    if entity_type not in access.readable_types:
        raise PermissionError("Entity type is not available to this caller")
    return ENTITY_SPECS[entity_type]


def _escaped_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_entity_query(
    entity_type: EntityType,
    filters: Mapping[str, object],
    access: InventoryAccess,
) -> EntityQueryPlan:
    """Build bounded-caller base and count plans for minimal entity reads.

    Supported filters are intentionally small: ``q`` and ``ids``. Domain list
    services own richer filters rather than accepting arbitrary field names.
    """
    spec = _require_readable(entity_type, access)
    unknown = set(filters) - {"q", "ids"}
    if unknown:
        raise ValueError(f"Unsupported entity filters: {', '.join(sorted(unknown))}")

    statement = select(spec.model)
    count_statement = select(func.count()).select_from(spec.model)
    predicates: list[Any] = []

    raw_query = filters.get("q")
    if raw_query is not None:
        query = str(raw_query).strip()
        if query:
            term = f"%{_escaped_like(query)}%"
            predicates.append(spec.model.name.ilike(term, escape="\\"))

    raw_ids = filters.get("ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
            raise ValueError("ids must be a sequence")
        ids = list(dict.fromkeys(int(value) for value in raw_ids))
        if len(ids) > _MAX_RESOLVE_REFS:
            raise ValueError(f"At most {_MAX_RESOLVE_REFS} entity references may be resolved")
        predicates.append(spec.model.id.in_(ids))

    if predicates:
        statement = statement.where(*predicates)
        count_statement = count_statement.where(*predicates)
    return EntityQueryPlan(statement=statement, count_statement=count_statement)


def _description(row: Any, spec: EntityQuerySpec) -> str | None:
    value = getattr(row, spec.description_attribute, None)
    return str(value) if value is not None else None


def _as_option(row: Any, spec: EntityQuerySpec) -> EntityOption:
    return EntityOption(
        ref=EntityRef(entity_type=spec.entity_type, entity_id=row.id),
        label=row.name,
        description=_description(row, spec),
    )


def resolve_entity_refs(
    db: Session,
    refs: Sequence[EntityRef],
    access: InventoryAccess,
) -> dict[str, EntityOption]:
    """Resolve bounded canonical references to authorized minimal metadata."""
    unique_refs = list(dict.fromkeys(refs))
    if len(unique_refs) > _MAX_RESOLVE_REFS:
        raise ValueError(f"At most {_MAX_RESOLVE_REFS} entity references may be resolved")

    grouped: dict[EntityType, list[int]] = defaultdict(list)
    for ref in unique_refs:
        if ref.entity_type in access.readable_types:
            grouped[ref.entity_type].append(ref.entity_id)

    resolved: dict[str, EntityOption] = {}
    for entity_type, ids in grouped.items():
        spec = ENTITY_SPECS[entity_type]
        statement = (
            select(spec.model)
            .where(spec.model.id.in_(ids))
            .order_by(func.lower(spec.model.name), spec.model.id)
        )
        for row in db.execute(statement).scalars():
            option = _as_option(row, spec)
            resolved[option.ref.key] = option
    return resolved


def _ranked_options(
    db: Session,
    entity_type: EntityType,
    query: str | None,
    access: InventoryAccess,
    limit: int,
) -> tuple[list[tuple[int, EntityOption]], bool]:
    spec = _require_readable(entity_type, access)
    lowered_name = func.lower(spec.model.name)
    statement = select(spec.model)
    normalized_query = (query or "").strip().lower()
    if normalized_query:
        escaped = _escaped_like(normalized_query)
        contains = f"%{escaped}%"
        prefix = f"{escaped}%"
        rank: ColumnElement[int] = case(
            (lowered_name == normalized_query, 0),
            (lowered_name.ilike(prefix, escape="\\"), 1),
            else_=2,
        )
        statement = statement.where(lowered_name.ilike(contains, escape="\\"))
    else:
        rank = literal(2)
    statement = statement.order_by(rank, lowered_name, spec.model.id).limit(limit + 1)
    rows = db.execute(statement).scalars().all()
    ranked = [
        (
            2 if not normalized_query else _rank(row.name, normalized_query),
            _as_option(row, spec),
        )
        for row in rows[:limit]
    ]
    return ranked, len(rows) > limit


def _rank(name: str, query: str) -> int:
    lowered = name.lower()
    if lowered == query:
        return 0
    if lowered.startswith(query):
        return 1
    return 2


def list_entity_options(
    db: Session,
    types: Sequence[EntityType],
    query: str | None,
    selected_refs: Sequence[EntityRef],
    action: SelectionAction,
    access: InventoryAccess,
    limit: int,
) -> EntityOptionResult:
    """Return globally ranked options and retain selected-value labels."""
    requested_types = list(dict.fromkeys(types))
    allowed_for_action = eligible_types(action)
    invalid = [
        entity_type for entity_type in requested_types if entity_type not in allowed_for_action
    ]
    if invalid:
        raise ValueError(f"Entity type is not eligible for {action}: {invalid[0]}")

    ranked: list[tuple[int, str, str, int, EntityOption]] = []
    any_type_has_more = False
    for entity_type in requested_types:
        if entity_type not in access.readable_types:
            continue
        options, type_has_more = _ranked_options(db, entity_type, query, access, limit)
        any_type_has_more = any_type_has_more or type_has_more
        ranked.extend(
            (rank, option.label.lower(), option.ref.entity_type, option.ref.entity_id, option)
            for rank, option in options
        )
    ranked.sort(key=lambda item: item[:4])
    items = [item[-1] for item in ranked[:limit]]
    has_more = any_type_has_more or len(ranked) > limit

    resolved = resolve_entity_refs(db, selected_refs, access)
    selected: list[EntityOption] = []
    for ref in selected_refs:
        option = resolved.get(ref.key)
        if option is not None:
            selected.append(option)
            continue
        readable = ref.entity_type in access.readable_types
        selected.append(
            EntityOption(
                ref=ref,
                label=f"Unavailable {ref.entity_type} #{ref.entity_id}",
                available=False,
                unavailable_reason="not_found" if readable else "unavailable",
            )
        )
    return EntityOptionResult(items=items, selected=selected, limit=limit, has_more=has_more)
