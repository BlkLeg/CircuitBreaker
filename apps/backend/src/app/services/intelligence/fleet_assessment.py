"""Fleet-wide vulnerability assessment.

The per-entity path (`cve_assessment.assess_entity`) answers "what about this
asset". This module answers "what about the fleet" without asking that question
once per asset: identities are resolved in bulk, collapsed to distinct tuples,
and matched with a single batched candidate query.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ComputeUnit, EntityAssessmentIdentity, Hardware, Service
from app.schemas.cve import AssessmentIdentity
from app.services.intelligence.cve_matching import infer_version_scheme

IdentityKey = tuple[str | None, str | None, str | None, str | None]


@dataclass(frozen=True)
class FleetEntity:
    """One assessable entity and the identity it resolved to."""

    entity_type: str
    entity_id: int
    name: str
    identity: AssessmentIdentity


def identity_key(identity: AssessmentIdentity) -> IdentityKey:
    """The tuple two entities must share to be assessed once instead of twice."""
    return (
        identity.vendor.casefold() if identity.vendor else None,
        identity.product.casefold() if identity.product else None,
        identity.version,
        identity.version_scheme,
    )


def _inventory_identity(
    vendor: str | None, product: str | None, version: str | None
) -> AssessmentIdentity:
    return AssessmentIdentity(
        vendor=vendor,
        product=product,
        version=version,
        version_scheme=infer_version_scheme(version),  # type: ignore[arg-type]
        provenance="inventory",
        revision=0,
    )


def resolve_fleet_identities(app_db: Session) -> list[FleetEntity]:
    """Resolve every assessable entity's identity in four queries.

    Mirrors `cve_assessment._entity_values` per type — hardware, compute units
    and services are the three types with an identity path. Storage has none.
    """
    overrides = {
        (row.entity_type, row.entity_id): row
        for row in app_db.query(EntityAssessmentIdentity).all()
    }

    entities: list[FleetEntity] = []

    def _append(entity_type: str, entity_id: int, name: str, base: AssessmentIdentity) -> None:
        override = overrides.get((entity_type, entity_id))
        identity = (
            AssessmentIdentity(
                vendor=override.vendor,
                product=override.product,
                version=override.version,
                version_scheme=override.version_scheme,  # type: ignore[arg-type]
                provenance="operator",
                revision=override.revision,
            )
            if override is not None
            else base
        )
        entities.append(FleetEntity(entity_type, entity_id, name, identity))

    for hardware in app_db.query(
        Hardware.id,
        Hardware.name,
        Hardware.vendor,
        Hardware.vendor_catalog_key,
        Hardware.model,
        Hardware.model_catalog_key,
        Hardware.software_platform,
        Hardware.os_version,
    ).all():
        _append(
            "hardware",
            hardware.id,
            hardware.name,
            _inventory_identity(
                hardware.vendor_catalog_key or hardware.vendor,
                hardware.model_catalog_key or hardware.model or hardware.software_platform,
                hardware.os_version,
            ),
        )

    for compute in app_db.query(ComputeUnit.id, ComputeUnit.name, ComputeUnit.os).all():
        _append(
            "compute_unit",
            compute.id,
            compute.name,
            _inventory_identity(None, compute.os, None),
        )

    for service in app_db.query(Service.id, Service.name).all():
        _append(
            "service",
            service.id,
            service.name,
            _inventory_identity(None, service.name, None),
        )

    return entities


def group_by_identity(entities: list[FleetEntity]) -> dict[IdentityKey, list[FleetEntity]]:
    """Collapse entities onto the identities that actually need assessing."""
    grouped: dict[IdentityKey, list[FleetEntity]] = defaultdict(list)
    for entity in entities:
        grouped[identity_key(entity.identity)].append(entity)
    return dict(grouped)
