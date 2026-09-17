"""Fleet-wide vulnerability assessment.

The per-entity path (`cve_assessment.assess_entity`) answers "what about this
asset". This module answers "what about the fleet" without asking that question
once per asset: identities are resolved in bulk, collapsed to distinct tuples,
and matched with a single batched candidate query.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.cve_models import CVEApplicability, CVENormalizedRecord
from app.db.models import ComputeUnit, EntityAssessmentIdentity, Hardware, Service
from app.schemas.cve import AssessmentIdentity
from app.services.intelligence.cve_assessment import MAX_CANDIDATES
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


PairKey = tuple[str | None, str]


@dataclass(frozen=True)
class CandidatePool:
    """Candidates for a whole pass, grouped by the (vendor, product) they matched."""

    by_pair: dict[PairKey, list[CVENormalizedRecord]]
    capped_pairs: set[PairKey]


def select_candidates(
    cache_db: Session,
    generation: str,
    product_keys: set[str],
) -> CandidatePool:
    """Select candidates for every product in the pass with one statement.

    The cap is applied per (vendor, product) pair inside the query rather than
    as one global LIMIT: a single noisy product would otherwise consume the
    whole budget and every other identity would silently come back empty.
    """
    if not product_keys:
        return CandidatePool(by_pair={}, capped_pairs=set())

    ranked = (
        select(
            CVEApplicability.record_id.label("record_id"),
            func.lower(CVEApplicability.vendor).label("vendor_key"),
            func.lower(CVEApplicability.product).label("product_key"),
            func.row_number()
            .over(
                partition_by=(
                    func.lower(CVEApplicability.vendor),
                    func.lower(CVEApplicability.product),
                ),
                order_by=(
                    CVENormalizedRecord.cvss_score.desc().nullslast(),
                    CVENormalizedRecord.id.asc(),
                ),
            )
            .label("rank"),
        )
        .join(CVENormalizedRecord, CVENormalizedRecord.id == CVEApplicability.record_id)
        .where(CVENormalizedRecord.generation_id == generation)
        .where(func.lower(CVEApplicability.product).in_(product_keys))
        .subquery()
    )
    rows = cache_db.execute(
        select(ranked.c.record_id, ranked.c.vendor_key, ranked.c.product_key, ranked.c.rank)
        .where(ranked.c.rank <= MAX_CANDIDATES + 1)
        .order_by(ranked.c.rank)
    ).all()

    capped_pairs: set[PairKey] = set()
    ids_by_pair: dict[PairKey, list[int]] = defaultdict(list)
    for record_id, vendor_key, product_key, rank in rows:
        pair: PairKey = (vendor_key, product_key)
        if rank > MAX_CANDIDATES:
            capped_pairs.add(pair)
            continue
        ids_by_pair[pair].append(record_id)

    wanted = {rid for ids in ids_by_pair.values() for rid in ids}
    # No selectinload of `.applicability` here, unlike the per-entity query:
    # matching reads only `configurations`, a JSON column on the record row,
    # and eager-loading the relationship would issue a second statement
    # against cve_applicability — a second scan for a relationship nobody
    # evaluates. The budget is one scan per pass.
    records = (
        cache_db.query(CVENormalizedRecord).filter(CVENormalizedRecord.id.in_(wanted)).all()
        if wanted
        else []
    )
    by_id = {record.id: record for record in records}
    by_pair = {
        pair: [by_id[rid] for rid in ids if rid in by_id] for pair, ids in ids_by_pair.items()
    }
    return CandidatePool(by_pair=by_pair, capped_pairs=capped_pairs)


def candidates_for(
    pool: CandidatePool, identity: AssessmentIdentity
) -> tuple[list[CVENormalizedRecord], bool]:
    """The candidates one identity should be evaluated against.

    An identity that names a vendor takes only its own pair. One that does not
    takes every vendor recorded for its product, which is what the per-entity
    query does when it omits the vendor filter.
    """
    if not identity.product:
        return [], False
    product_key = identity.product.casefold()
    vendor_key = identity.vendor.casefold() if identity.vendor else None
    pairs = (
        [(vendor_key, product_key)]
        if vendor_key is not None
        else [pair for pair in pool.by_pair if pair[1] == product_key]
    )
    seen: set[int] = set()
    records: list[CVENormalizedRecord] = []
    limited = False
    for pair in pairs:
        if pair in pool.capped_pairs:
            limited = True
        for record in pool.by_pair.get(pair, []):
            if record.id not in seen:
                seen.add(record.id)
                records.append(record)
    if len(records) > MAX_CANDIDATES:
        records = records[:MAX_CANDIDATES]
        limited = True
    return records, limited
