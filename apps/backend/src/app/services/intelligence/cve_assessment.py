"""Entity identity, feed readiness, and vulnerability assessment orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, NotFoundError
from app.db.cve_models import CVEApplicability, CVEFeedGeneration, CVENormalizedRecord
from app.db.models import (
    AppSettings,
    ComputeUnit,
    EntityAssessmentIdentity,
    Hardware,
    Service,
)
from app.schemas.cve import (
    ApplicabilityEvidence,
    AssessmentIdentity,
    AssessmentResult,
    FeedState,
    IdentityPatch,
    VulnerabilityFinding,
)
from app.services.intelligence.cve_feed import active_feed_generation
from app.services.intelligence.cve_matching import (
    evaluate_applicability,
    infer_version_scheme,
)

MAX_CANDIDATES = 1000
MAX_FINDINGS = 50


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _entity_values(app_db: Session, entity_type: str, entity_id: int) -> tuple[Any, ...]:
    if entity_type == "hardware":
        hardware = app_db.get(Hardware, entity_id)
        if hardware is None:
            raise NotFoundError("Hardware not found.")
        return (
            hardware.vendor_catalog_key or hardware.vendor,
            hardware.model_catalog_key or hardware.model or hardware.software_platform,
            hardware.os_version,
        )
    if entity_type == "compute_unit":
        compute = app_db.get(ComputeUnit, entity_id)
        if compute is None:
            raise NotFoundError("Compute unit not found.")
        return (None, compute.os, None)
    if entity_type == "service":
        service = app_db.get(Service, entity_id)
        if service is None:
            raise NotFoundError("Service not found.")
        return (None, service.name, None)
    raise NotFoundError("Entity type is not supported for vulnerability assessment.")


def resolve_assessment_identity(
    app_db: Session, entity_type: str, entity_id: int
) -> AssessmentIdentity:
    inventory_values = _entity_values(app_db, entity_type, entity_id)
    override = (
        app_db.query(EntityAssessmentIdentity)
        .filter(
            EntityAssessmentIdentity.entity_type == entity_type,
            EntityAssessmentIdentity.entity_id == entity_id,
        )
        .one_or_none()
    )
    if override is not None:
        return AssessmentIdentity(
            vendor=override.vendor,
            product=override.product,
            version=override.version,
            version_scheme=override.version_scheme,  # type: ignore[arg-type]
            provenance="operator",
            revision=override.revision,
        )
    vendor, product, version = inventory_values
    return AssessmentIdentity(
        vendor=vendor,
        product=product,
        version=version,
        version_scheme=infer_version_scheme(version),  # type: ignore[arg-type]
        provenance="inventory",
        revision=1,
    )


def update_assessment_identity(
    app_db: Session,
    entity_type: str,
    entity_id: int,
    patch: IdentityPatch,
    *,
    actor: str | None,
) -> AssessmentIdentity:
    _entity_values(app_db, entity_type, entity_id)
    row = (
        app_db.query(EntityAssessmentIdentity)
        .filter(
            EntityAssessmentIdentity.entity_type == entity_type,
            EntityAssessmentIdentity.entity_id == entity_id,
        )
        .with_for_update()
        .one_or_none()
    )
    current_revision = row.revision if row is not None else 0
    if patch.revision != current_revision:
        raise ConflictError(
            "The assessment identity changed. Reload it and try again.",
            error_code="stale_identity",
        )
    scheme = patch.version_scheme or infer_version_scheme(patch.version)
    if row is None:
        row = EntityAssessmentIdentity(
            entity_type=entity_type,
            entity_id=entity_id,
            revision=1,
        )
        app_db.add(row)
    else:
        row.revision += 1
    row.vendor = patch.vendor
    row.product = patch.product
    row.version = patch.version
    row.version_scheme = scheme
    row.provenance = "operator"
    row.updated_by = actor
    app_db.flush()
    return AssessmentIdentity(
        vendor=row.vendor,
        product=row.product,
        version=row.version,
        version_scheme=row.version_scheme,  # type: ignore[arg-type]
        provenance="operator",
        revision=row.revision,
    )


def get_feed_state(
    cache_db: Session,
    settings: AppSettings | None,
    now: datetime,
) -> FeedState:
    generation = active_feed_generation(cache_db)
    latest_attempt = (
        cache_db.query(CVEFeedGeneration).order_by(CVEFeedGeneration.started_at.desc()).first()
    )
    if generation is None:
        return FeedState(
            state="incomplete" if latest_attempt is not None else "unavailable",
            reason_code="feed_incomplete" if latest_attempt is not None else "feed_missing",
            coverage_complete=False,
            last_attempt_at=_aware(latest_attempt.started_at) if latest_attempt else None,
        )
    completed_at = _aware(generation.completed_at)
    age_seconds = max(0, int((now - completed_at).total_seconds())) if completed_at else None
    interval_hours = settings.cve_sync_interval_hours if settings else 24
    stale_after = max(24, interval_hours * 2) * 3600
    stale = age_seconds is None or age_seconds > stale_after
    return FeedState(
        state="stale" if stale else "ready",
        reason_code="feed_stale" if stale else "ready",
        generation=generation.id,
        completed_at=completed_at,
        age_seconds=age_seconds,
        total_records=generation.records_stored,
        coverage_complete=True,
        last_attempt_at=_aware(latest_attempt.started_at) if latest_attempt else None,
        last_success_at=completed_at,
    )


def assess_entity(
    app_db: Session,
    cache_db: Session,
    entity_type: str,
    entity_id: int,
    *,
    now: datetime | None = None,
) -> AssessmentResult:
    assessed_at = now or datetime.now(UTC)
    identity = resolve_assessment_identity(app_db, entity_type, entity_id)
    settings = app_db.query(AppSettings).first()
    feed = get_feed_state(cache_db, settings, assessed_at)
    if feed.state in {"unavailable", "incomplete"}:
        return AssessmentResult(
            state="unavailable",
            reason_code=feed.reason_code,  # type: ignore[arg-type]
            identity=identity,
            identity_revision=identity.revision,
            feed_generation=feed.generation,
            feed_age_seconds=feed.age_seconds,
            assessed_at=assessed_at,
            findings=[],
            total=0,
            completeness="none",
            limitations=["A complete vulnerability feed is not available."],
        )
    if not identity.product:
        return AssessmentResult(
            state="unassessed",
            reason_code="identity_missing",
            identity=identity,
            identity_revision=identity.revision,
            feed_generation=feed.generation,
            feed_age_seconds=feed.age_seconds,
            assessed_at=assessed_at,
            findings=[],
            total=0,
            completeness="none",
            limitations=["A product identity is required before matching."],
        )
    if not identity.version:
        return AssessmentResult(
            state="unassessed",
            reason_code="version_missing",
            identity=identity,
            identity_revision=identity.revision,
            feed_generation=feed.generation,
            feed_age_seconds=feed.age_seconds,
            assessed_at=assessed_at,
            findings=[],
            total=0,
            completeness="none",
            limitations=["A product version is required before matching."],
        )
    if not identity.version_scheme:
        return AssessmentResult(
            state="unassessed",
            reason_code="version_unsupported",
            identity=identity,
            identity_revision=identity.revision,
            feed_generation=feed.generation,
            feed_age_seconds=feed.age_seconds,
            assessed_at=assessed_at,
            findings=[],
            total=0,
            completeness="none",
            limitations=["This version format does not have a supported comparator."],
        )

    query = (
        cache_db.query(CVENormalizedRecord)
        .join(CVEApplicability)
        .filter(CVENormalizedRecord.generation_id == feed.generation)
        .filter(func.lower(CVEApplicability.product) == identity.product.casefold())
    )
    if identity.vendor:
        query = query.filter(func.lower(CVEApplicability.vendor) == identity.vendor.casefold())
    candidates = (
        query.options(selectinload(CVENormalizedRecord.applicability))
        .order_by(CVENormalizedRecord.cvss_score.desc().nullslast())
        .distinct()
        .limit(MAX_CANDIDATES + 1)
        .all()
    )
    candidate_limited = len(candidates) > MAX_CANDIDATES
    candidates = candidates[:MAX_CANDIDATES]
    findings: list[VulnerabilityFinding] = []
    limitations: set[str] = set()
    unknown = False
    identity_dict = identity.model_dump()
    for candidate in candidates:
        result = evaluate_applicability(candidate.configurations, identity_dict)
        limitations.update(result.limitations)
        if result.result == "unknown":
            unknown = True
        elif result.result == "true":
            findings.append(
                VulnerabilityFinding(
                    cve_id=candidate.cve_id,
                    severity=candidate.severity,
                    cvss_score=candidate.cvss_score,
                    summary=candidate.summary,
                    published_at=_aware(candidate.published_at),
                    updated_at=_aware(candidate.updated_at),
                    evidence=[
                        ApplicabilityEvidence.model_validate(item) for item in result.evidence
                    ],
                )
            )
    finding_limited = len(findings) > MAX_FINDINGS
    findings = findings[:MAX_FINDINGS]
    if candidate_limited:
        limitations.add("Candidate limit reached; coverage is partial.")
    if finding_limited:
        limitations.add("Only the first 50 findings are returned.")
    partial = candidate_limited or finding_limited or unknown
    state = "partial" if partial else ("stale" if feed.state == "stale" else "completed")
    reason = (
        "candidate_limit"
        if candidate_limited
        else (
            "feed_stale"
            if feed.state == "stale"
            else ("version_unsupported" if unknown else "completed")
        )
    )
    return AssessmentResult(
        state=state,  # type: ignore[arg-type]
        reason_code=reason,  # type: ignore[arg-type]
        identity=identity,
        identity_revision=identity.revision,
        feed_generation=feed.generation,
        feed_age_seconds=feed.age_seconds,
        assessed_at=assessed_at,
        findings=findings,
        total=len(findings),
        completeness="partial" if partial else "complete",
        limitations=sorted(limitations),
    )
