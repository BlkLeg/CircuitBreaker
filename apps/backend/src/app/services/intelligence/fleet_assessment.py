"""Fleet-wide vulnerability assessment.

The per-entity path (`cve_assessment.assess_entity`) answers "what about this
asset". This module answers "what about the fleet" without asking that question
once per asset: identities are resolved in bulk, collapsed to distinct tuples,
and matched with a single batched candidate query.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.cve_models import CVEApplicability, CVENormalizedRecord
from app.db.models import (
    AppSettings,
    ComputeUnit,
    EntityAssessmentIdentity,
    Hardware,
    Service,
)
from app.schemas.cve import (
    AssessmentIdentity,
    AssessmentResult,
    FleetAssessment,
    FleetAssessmentLimits,
    FleetAssessmentRow,
    FleetAssessmentSummary,
    VulnerabilityFinding,
)
from app.services.intelligence.cve_assessment import (
    MAX_CANDIDATES,
    evaluate_candidates,
    get_feed_state,
    readiness_result,
)
from app.services.intelligence.cve_matching import infer_version_scheme
from app.services.intelligence.fleet_cache import (
    cached_outcome,
    identity_cache_key,
    remember_outcome,
)

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


DEFAULT_IDENTITY_LIMIT = 250

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _worst(findings: list[VulnerabilityFinding]) -> tuple[str | None, float | None]:
    """The severity and score a row leads with: its worst finding."""
    severity: str | None = None
    score: float | None = None
    for finding in findings:
        current = (finding.severity or "").casefold() or None
        if current and SEVERITY_RANK.get(current, 0) > SEVERITY_RANK.get(severity or "", 0):
            severity = current
        if finding.cvss_score is not None and (score is None or finding.cvss_score > score):
            score = finding.cvss_score
    return severity, score


def _row(entity: FleetEntity, result: AssessmentResult) -> FleetAssessmentRow:
    """Project one entity's share of a group's assessment onto a table row.

    The identity comes from the entity, never from `result`. A group is keyed on
    identity *values*, so its members can differ in provenance and revision — one
    read from inventory, one corrected by an operator to the same values. Taking
    the representative's identity reported the wrong revision for every other
    member, and the revision is what a correction sends back: the next correction
    of that entity would conflict with itself.
    """
    severity, score = _worst(result.findings)
    return FleetAssessmentRow(
        entity_type=entity.entity_type,
        entity_id=entity.entity_id,
        name=entity.name,
        state=result.state,
        reason_code=result.reason_code,
        identity=entity.identity,
        finding_count=result.total,
        max_severity=severity,
        max_cvss=score,
        completeness=result.completeness,
    )


def _over_budget(entity: FleetEntity, assessed_at: datetime) -> AssessmentResult:
    return AssessmentResult(
        state="unassessed",
        reason_code="fleet_limit",
        identity=entity.identity,
        identity_revision=entity.identity.revision,
        feed_generation=None,
        feed_age_seconds=None,
        assessed_at=assessed_at,
        findings=[],
        total=0,
        completeness="none",
        limitations=["The fleet pass reached its per-request identity budget."],
    )


def assess_fleet(
    app_db: Session,
    cache_db: Session,
    *,
    now: datetime | None = None,
    identity_limit: int = DEFAULT_IDENTITY_LIMIT,
) -> FleetAssessment:
    """Assess every assessable entity, once per distinct identity."""
    assessed_at = now or datetime.now(UTC)
    settings = app_db.query(AppSettings).first()
    feed = get_feed_state(cache_db, settings, assessed_at)
    entities = resolve_fleet_identities(app_db)
    grouped = group_by_identity(entities)

    ordered_keys = sorted(grouped, key=lambda key: tuple("" if p is None else p for p in key))
    assessed_keys = ordered_keys[:identity_limit]
    deferred_keys = ordered_keys[identity_limit:]

    pool = CandidatePool(by_pair={}, capped_pairs=set())
    if feed.generation is not None:
        products = {
            key[1]
            for key in assessed_keys
            if key[1] is not None
            and readiness_result(grouped[key][0].identity, feed, assessed_at) is None
        }
        pool = select_candidates(cache_db, feed.generation, products)

    rows: list[FleetAssessmentRow] = []
    capped_products: set[str] = set()
    for key in assessed_keys:
        members = grouped[key]
        identity = members[0].identity
        blocked = readiness_result(identity, feed, assessed_at)
        if blocked is not None:
            result = blocked
        else:
            cache_key = (
                identity_cache_key(feed.generation, feed.state, key)
                if feed.generation is not None
                else None
            )
            cached = cached_outcome(cache_key) if cache_key is not None else None
            if cached is not None:
                result = cached.model_copy(
                    update={"assessed_at": assessed_at, "feed_age_seconds": feed.age_seconds}
                )
            else:
                candidates, limited = candidates_for(pool, identity)
                result = evaluate_candidates(
                    candidates, identity, feed, assessed_at, candidate_limited=limited
                )
                if cache_key is not None:
                    remember_outcome(cache_key, result)
        # Read the caveat off the result rather than off the branch that
        # produced it. `evaluate_candidates` emits `candidate_limit` exactly when
        # it was limited, so a cached outcome carries the fact too — collecting
        # it only where candidates were selected meant a warm pass dropped the
        # caveat while its rows still said `partial`.
        if result.reason_code == "candidate_limit" and identity.product:
            capped_products.add(identity.product)
        for entity in members:
            rows.append(_row(entity, result))
    for key in deferred_keys:
        for entity in grouped[key]:
            rows.append(_row(entity, _over_budget(entity, assessed_at)))

    by_state: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for row in rows:
        by_state[row.state] += 1
        if row.max_severity:
            by_severity[row.max_severity] += 1

    return FleetAssessment(
        feed=feed,
        assessed_at=assessed_at,
        summary=FleetAssessmentSummary(
            total_entities=len(rows),
            by_state=dict(by_state),
            entities_with_findings=sum(1 for row in rows if row.finding_count > 0),
            findings_total=sum(row.finding_count for row in rows),
            by_severity=dict(by_severity),
        ),
        rows=rows,
        limits=FleetAssessmentLimits(
            identity_limit=identity_limit,
            identities_total=len(ordered_keys),
            identities_assessed=len(assessed_keys),
            identity_limit_reached=bool(deferred_keys),
            candidate_limited_products=sorted(capped_products),
        ),
    )
