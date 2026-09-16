"""Read-only counts behind the inventory transfer summary strip."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.schemas.inventory_transfer import TransferSummary
from app.services.inventory_transfer.export import _ENTITY_MODELS, _RELATION_MODELS

#: The seven asset kinds the summary tile counts; docs, tags and clusters are
#: portable too but are supporting data, not assets.
ASSET_KINDS = (
    "hardware",
    "compute_units",
    "services",
    "storage",
    "networks",
    "misc_items",
    "external_nodes",
)


def summary_counts(db: Session) -> TransferSummary:
    """Count every declared portable kind. One bounded query per kind."""
    assets = {
        name: db.query(model).count()
        for name, model in _ENTITY_MODELS.items()
        if name in ASSET_KINDS
    }
    relationships = {name: db.query(model).count() for name, model in _RELATION_MODELS.items()}
    return TransferSummary(
        format="circuitbreaker.inventory",
        version=1,
        assets=assets,
        assets_total=sum(assets.values()),
        relationships=relationships,
        relationships_total=sum(relationships.values()),
    )
