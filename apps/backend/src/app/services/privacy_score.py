"""Privacy score orchestrator: rules over scan data → per-device scores + snapshot.

Two entrypoints:
- ``recompute_all(db)`` — full pass (device scores + network checks + snapshot);
  fired from the discovery scan-finalize hook.
- ``run_privacy_periodic_job()`` — lightweight periodic pass (feed refresh +
  network checks + snapshot from stored device profiles); APScheduler-hosted.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import desc
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    AppSettings,
    Hardware,
    NetworkPrivacySnapshot,
    PrivacyScoreHistory,
    ScanResult,
)
from app.services import privacy_rules
from app.services.network_checks import run_all_checks
from app.services.threat_feed import get_feed

logger = logging.getLogger(__name__)


def _open_session() -> Session:
    from app.db.session import SessionLocal

    return SessionLocal()


def _parse_ports(raw: list | str | None) -> set[int]:
    if not raw:
        return set()
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return set()
    ports: set[int] = set()
    for entry in raw:
        try:
            port = int(entry.get("port", 0)) if isinstance(entry, dict) else int(entry)
        except (TypeError, ValueError):
            continue
        if port:
            ports.add(port)
    return ports


def _open_ports_for(db: Session, hardware: Hardware) -> set[int]:
    """Latest matched scan result's open ports for one device (scan-proven only)."""
    scan_result = (
        db.query(ScanResult)
        .filter(
            ScanResult.matched_entity_type == "hardware",
            ScanResult.matched_entity_id == hardware.id,
        )
        .order_by(desc(ScanResult.id))
        .first()
    )
    if scan_result is None and hardware.source_scan_result_id:
        scan_result = db.get(ScanResult, hardware.source_scan_result_id)
    if scan_result is None:
        return set()
    return _parse_ports(scan_result.open_ports_json)


def _score_devices(db: Session) -> list[dict]:
    """Score every real device; persist score, profile, and a history row each."""
    all_deductions: list[dict] = []
    devices = db.query(Hardware).filter(Hardware.is_placeholder.is_(False)).all()
    for hardware in devices:
        deductions = privacy_rules.evaluate_device(
            hardware.id, hardware.role, _open_ports_for(db, hardware)
        )
        hardware.privacy_score = privacy_rules.score_device(deductions)
        hardware.threat_profile = deductions
        db.add(
            PrivacyScoreHistory(
                hardware_id=hardware.id, score=hardware.privacy_score, threat_profile=deductions
            )
        )
        all_deductions.extend(deductions)
    return all_deductions


def _stored_device_deductions(db: Session) -> list[dict]:
    """Flatten the deduction lists already stored on hardware.threat_profile."""
    profiles = db.query(Hardware.threat_profile).filter(Hardware.threat_profile.isnot(None)).all()
    return [deduction for (profile,) in profiles for deduction in (profile or [])]


def _write_snapshot(db: Session, device_deductions: list[dict], checks: list[dict]) -> dict:
    snapshot = privacy_rules.evaluate_network(device_deductions, checks)
    db.add(
        NetworkPrivacySnapshot(
            score=snapshot["score"],
            grade=snapshot["grade"],
            deductions=snapshot["deductions"],
            checks=snapshot["checks"],
        )
    )
    return snapshot


def _load_enabled_settings(db: Session) -> AppSettings | None:
    settings_row = db.query(AppSettings).first()
    if settings_row is None or not settings_row.windscribe_enabled:
        return None
    return settings_row


async def recompute_all(db: Session) -> dict | None:
    """Full recompute: device rules + network checks + one snapshot row.

    Returns the snapshot dict, or None when the integration is disabled.
    """
    settings_row = _load_enabled_settings(db)
    if settings_row is None:
        return None
    try:
        device_deductions = _score_devices(db)
        feed = await get_feed(settings_row.windscribe_feed_refresh_hours or 1)
        checks = await run_all_checks(feed)
        snapshot = _write_snapshot(db, device_deductions, checks)
        db.commit()
        return snapshot
    except SQLAlchemyError as exc:
        logger.error("[privacy_score] recompute failed, rolling back: %s", exc)
        db.rollback()
        raise


async def run_privacy_periodic_job() -> None:
    """Periodic pass: refresh feed + network checks; device scores stay scan-driven."""
    db = _open_session()
    try:
        settings_row = _load_enabled_settings(db)
        if settings_row is None:
            return
        feed = await get_feed(settings_row.windscribe_feed_refresh_hours or 1)
        checks = await run_all_checks(feed)
        _write_snapshot(db, _stored_device_deductions(db), checks)
        db.commit()
    except SQLAlchemyError as exc:
        logger.error("[privacy_score] periodic job DB failure: %s", exc)
        db.rollback()
    except Exception as exc:  # never let the scheduler job die noisily
        logger.error("[privacy_score] periodic job failed: %s", exc, exc_info=True)
    finally:
        db.close()
