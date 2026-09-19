"""Normalized CVE feed ingestion with complete-generation activation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.cve_models import CVEApplicability, CVEFeedGeneration, CVENormalizedRecord
from app.services.intelligence.cve_matching import NormalizedCVE, flatten_applicability


@dataclass(frozen=True)
class PageSummary:
    seen: int
    stored: int
    parse_failures: int


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def parse_nvd_record(record: dict[str, Any]) -> NormalizedCVE | None:
    """Preserve the complete NVD configuration tree for later evaluation."""
    cve = record.get("cve", record)
    cve_id = cve.get("id")
    if not isinstance(cve_id, str) or not cve_id:
        return None
    descriptions = cve.get("descriptions") or []
    summary = next((item.get("value") for item in descriptions if item.get("lang") == "en"), None)
    metrics = cve.get("metrics") or {}
    score: float | None = None
    severity: str | None = None
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        values = metrics.get(key) or []
        if values:
            data = values[0].get("cvssData") or {}
            raw_score = data.get("baseScore")
            score = float(raw_score) if raw_score is not None else None
            raw_severity = data.get("baseSeverity") or values[0].get("baseSeverity")
            severity = str(raw_severity).lower() if raw_severity else None
            break
    configurations = cve.get("configurations") or []
    if not isinstance(configurations, list):
        configurations = []
    return NormalizedCVE(
        cve_id=cve_id,
        severity=severity,
        cvss_score=score,
        summary=str(summary) if summary is not None else None,
        published_at=_parse_dt(cve.get("published")),
        updated_at=_parse_dt(cve.get("lastModified")),
        configurations=configurations,
    )


def start_feed_generation(cache_db: Session, *, source: str = "nvd") -> CVEFeedGeneration:
    generation = CVEFeedGeneration(
        id=uuid4().hex,
        source=source,
        status="running",
        started_at=datetime.now(UTC),
    )
    cache_db.add(generation)
    cache_db.flush()
    return generation


def ingest_feed_page(
    cache_db: Session,
    generation: CVEFeedGeneration,
    records: list[dict[str, Any]],
) -> PageSummary:
    """Idempotently replace records for one generation; caller owns commit."""
    stored = 0
    failures = 0
    for raw in records:
        parsed = parse_nvd_record(raw)
        if parsed is None:
            failures += 1
            continue
        row = (
            cache_db.query(CVENormalizedRecord)
            .filter(
                CVENormalizedRecord.generation_id == generation.id,
                CVENormalizedRecord.cve_id == parsed.cve_id,
            )
            .one_or_none()
        )
        if row is None:
            row = CVENormalizedRecord(generation_id=generation.id, cve_id=parsed.cve_id)
            cache_db.add(row)
        row.severity = parsed.severity
        row.cvss_score = parsed.cvss_score
        row.summary = parsed.summary
        row.published_at = parsed.published_at
        row.updated_at = parsed.updated_at
        row.configurations = parsed.configurations
        cache_db.flush()
        row.applicability.clear()
        for match in flatten_applicability(parsed.configurations):
            row.applicability.append(CVEApplicability(**match))
        stored += 1
    generation.records_seen += len(records)
    generation.records_stored += stored
    generation.parse_failures += failures
    cache_db.flush()
    return PageSummary(seen=len(records), stored=stored, parse_failures=failures)


def complete_feed_generation(
    cache_db: Session,
    generation: CVEFeedGeneration,
    *,
    total_records: int,
) -> None:
    """Activate only a fully enumerated, fully parsed generation."""
    generation.total_records = total_records
    generation.completed_at = datetime.now(UTC)
    generation.coverage_complete = (
        total_records > 0
        and generation.records_seen >= total_records
        and generation.parse_failures == 0
    )
    generation.status = "complete" if generation.coverage_complete else "incomplete"
    cache_db.flush()


def fail_feed_generation(
    cache_db: Session, generation: CVEFeedGeneration, *, safe_error: str
) -> None:
    generation.status = "failed"
    generation.completed_at = datetime.now(UTC)
    generation.coverage_complete = False
    generation.safe_error = safe_error[:300]
    cache_db.flush()


def active_feed_generation(cache_db: Session) -> CVEFeedGeneration | None:
    return (
        cache_db.query(CVEFeedGeneration)
        .filter(
            CVEFeedGeneration.status == "complete",
            CVEFeedGeneration.coverage_complete.is_(True),
        )
        .order_by(CVEFeedGeneration.completed_at.desc())
        .first()
    )
