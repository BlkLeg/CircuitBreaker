"""CVE ingestion and lookup service.

Fetches vulnerability data from the NVD 2.0 API, stores it in the dedicated
CVE database (``data/cve.db``), and provides lookup functions that map
vendor/product/version tuples to known CVEs.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import func

from app.core.time import utcnow_iso
from app.db.cve_session import CVESessionLocal
from app.db.models import AppSettings, CVEEntry
from app.db.session import SessionLocal
from app.services.log_service import write_log

_logger = logging.getLogger(__name__)

NVD_API_BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_PAGE_SIZE = 200
_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def lookup_cves(
    vendor: str | None = None,
    product: str | None = None,
    version: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Return CVEs matching the given vendor/product/version filters.

    Version matching is approximate: if *version* falls within
    ``[version_start, version_end]`` lexicographically the CVE is included.
    """
    with CVESessionLocal() as db:
        q = db.query(CVEEntry)
        if vendor:
            q = q.filter(func.lower(CVEEntry.vendor) == vendor.lower())
        if product:
            q = q.filter(func.lower(CVEEntry.product) == product.lower())
        if version:
            q = q.filter(
                (CVEEntry.version_start.is_(None) | (CVEEntry.version_start <= version)),
                (CVEEntry.version_end.is_(None) | (CVEEntry.version_end >= version)),
            )
        rows = (
            q.order_by(CVEEntry.cvss_score.desc().nullslast(), CVEEntry.cve_id).limit(limit).all()
        )
        return [_row_to_dict(r) for r in rows]


def search_cves(
    query: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    severity: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Free-text + filter search across CVE entries. Returns ``(results, total)``."""
    with CVESessionLocal() as db:
        q = db.query(CVEEntry)
        if vendor:
            q = q.filter(func.lower(CVEEntry.vendor) == vendor.lower())
        if product:
            q = q.filter(func.lower(CVEEntry.product) == product.lower())
        if severity:
            q = q.filter(func.lower(CVEEntry.severity) == severity.lower())
        if query:
            pattern = f"%{query}%"
            q = q.filter(
                CVEEntry.cve_id.ilike(pattern)
                | CVEEntry.summary.ilike(pattern)
                | CVEEntry.vendor.ilike(pattern)
                | CVEEntry.product.ilike(pattern)
            )
        total = q.count()
        rows = (
            q.order_by(CVEEntry.cvss_score.desc().nullslast(), CVEEntry.cve_id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [_row_to_dict(r) for r in rows], total


def cves_for_entity(entity_type: str, entity_id: int) -> list[dict]:
    """Return CVEs relevant to a specific entity by looking up its vendor/model/OS."""
    with SessionLocal() as db:
        vendor, product, version = _resolve_entity(db, entity_type, entity_id)
    if not vendor and not product:
        return []
    return lookup_cves(vendor=vendor, product=product, version=version)


def get_status() -> dict:
    """Return sync status: last sync time, total entries, enabled flag."""
    with SessionLocal() as db:
        settings = db.query(AppSettings).first()
        enabled = settings.cve_sync_enabled if settings else False
        last_sync = settings.cve_last_sync_at if settings else None
        interval = settings.cve_sync_interval_hours if settings else 24

    with CVESessionLocal() as db:
        total = db.query(func.count(CVEEntry.id)).scalar() or 0

    return {
        "enabled": enabled,
        "last_sync_at": last_sync,
        "sync_interval_hours": interval,
        "total_entries": total,
    }


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def sync_nvd_feed() -> int:
    """Fetch the NVD CVE feed and upsert entries into the CVE database.

    Returns the number of entries upserted.
    """
    _logger.info("Starting NVD CVE feed sync")
    upserted = 0
    start_index = 0

    try:
        while True:
            params = {
                "startIndex": start_index,
                "resultsPerPage": _PAGE_SIZE,
            }
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(NVD_API_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()

            vulnerabilities = data.get("vulnerabilities", [])
            if not vulnerabilities:
                break

            entries = []
            for item in vulnerabilities:
                cve = item.get("cve", {})
                parsed = _parse_nvd_cve(cve)
                if parsed:
                    entries.append(parsed)

            if entries:
                upserted += _upsert_entries(entries)

            total_results = data.get("totalResults", 0)
            start_index += _PAGE_SIZE
            if start_index >= total_results:
                break

        _record_sync_timestamp()
        _logger.info("NVD sync complete: %d entries upserted", upserted)

        write_log(
            db=None,
            action="cve_sync_completed",
            category="settings",
            severity="info",
            details=f"NVD CVE sync completed: {upserted} entries upserted",
        )
    except Exception as exc:
        _logger.error("NVD CVE sync failed: %s", exc, exc_info=True)
        write_log(
            db=None,
            action="cve_sync_failed",
            category="settings",
            severity="error",
            details=f"NVD CVE sync failed: {exc}",
        )
        raise

    return upserted


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _parse_nvd_cve(cve: dict) -> dict | None:
    """Parse a single NVD CVE JSON object into a flat dict for upsert."""
    cve_id = cve.get("id")
    if not cve_id:
        return None

    descriptions = cve.get("descriptions", [])
    summary = next((d["value"] for d in descriptions if d.get("lang") == "en"), None)

    metrics = cve.get("metrics", {})
    cvss_score = None
    severity = None

    for version_key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        metric_list = metrics.get(version_key, [])
        if metric_list:
            cvss_data = metric_list[0].get("cvssData", {})
            cvss_score = cvss_data.get("baseScore")
            severity = cvss_data.get("baseSeverity", "").lower() or None
            break

    vendor = None
    product = None
    version_start = None
    version_end = None
    configurations = cve.get("configurations", [])
    for config in configurations:
        for node in config.get("nodes", []):
            for cpe_match in node.get("cpeMatch", []):
                cpe_uri = cpe_match.get("criteria", "")
                parts = cpe_uri.split(":")
                if len(parts) >= 5:
                    vendor = parts[3] if parts[3] != "*" else None
                    product = parts[4] if parts[4] != "*" else None
                version_start = cpe_match.get("versionStartIncluding")
                version_end = cpe_match.get("versionEndIncluding") or cpe_match.get(
                    "versionEndExcluding"
                )
                break
            if vendor or product:
                break
        if vendor or product:
            break

    published = cve.get("published")
    last_modified = cve.get("lastModified")

    return {
        "cve_id": cve_id,
        "vendor": vendor,
        "product": product,
        "version_start": version_start,
        "version_end": version_end,
        "severity": severity,
        "cvss_score": cvss_score,
        "summary": summary,
        "published_at": _parse_dt(published),
        "updated_at": _parse_dt(last_modified),
    }


def _upsert_entries(entries: list[dict]) -> int:
    """Insert or update CVE entries. Returns number of rows affected."""
    count = 0
    with CVESessionLocal() as db:
        for entry in entries:
            existing = db.query(CVEEntry).filter(CVEEntry.cve_id == entry["cve_id"]).first()
            if existing:
                for key, value in entry.items():
                    if key != "cve_id":
                        setattr(existing, key, value)
            else:
                db.add(CVEEntry(**entry))
            count += 1
        db.commit()
    return count


def _record_sync_timestamp() -> None:
    with SessionLocal() as db:
        settings = db.query(AppSettings).first()
        if settings:
            settings.cve_last_sync_at = utcnow_iso()
            db.commit()


def _resolve_entity(
    db: Any, entity_type: str, entity_id: int
) -> tuple[str | None, str | None, str | None]:
    """Extract vendor/product/version from an entity for CVE lookup."""
    if entity_type == "hardware":
        from app.db.models import Hardware

        hw = db.query(Hardware).filter(Hardware.id == entity_id).first()
        if hw:
            return (
                hw.vendor_catalog_key or (hw.vendor if hasattr(hw, "vendor") else None),
                hw.model_catalog_key or (hw.model if hasattr(hw, "model") else None),
                hw.os_version if hasattr(hw, "os_version") else None,
            )
    elif entity_type == "compute_unit":
        from app.db.models import ComputeUnit

        cu = db.query(ComputeUnit).filter(ComputeUnit.id == entity_id).first()
        if cu:
            return (None, cu.os if hasattr(cu, "os") else None, None)
    elif entity_type == "service":
        from app.db.models import Service

        svc = db.query(Service).filter(Service.id == entity_id).first()
        if svc:
            return (None, svc.name, None)
    return (None, None, None)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _row_to_dict(row: CVEEntry) -> dict:
    return {
        "id": row.id,
        "cve_id": row.cve_id,
        "vendor": row.vendor,
        "product": row.product,
        "version_start": row.version_start,
        "version_end": row.version_end,
        "severity": row.severity,
        "cvss_score": row.cvss_score,
        "summary": row.summary,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
