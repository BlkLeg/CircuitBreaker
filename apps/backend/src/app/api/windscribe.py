"""Privacy & threat endpoints — served from the latest snapshot, never computed
on request. Disabled/no-data states return 200 empty shapes, not errors."""

from collections import Counter
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_auth
from app.core.time import utcnow
from app.db.models import AppSettings, Hardware, NetworkPrivacySnapshot, ScanResult
from app.db.session import get_db

router = APIRouter()

_HISTORY_LIMIT = 30
_SCORE_HISTORY_DAYS_MAX = 90


def _is_windscribe_enabled(db: Session) -> bool:
    settings_row = db.query(AppSettings).first()
    return bool(settings_row and settings_row.windscribe_enabled)


def _latest_snapshot(db: Session) -> NetworkPrivacySnapshot | None:
    return db.query(NetworkPrivacySnapshot).order_by(NetworkPrivacySnapshot.id.desc()).first()


def _score_history(db: Session) -> list[dict]:
    rows = (
        db.query(NetworkPrivacySnapshot.score, NetworkPrivacySnapshot.created_at)
        .order_by(NetworkPrivacySnapshot.id.desc())
        .limit(_HISTORY_LIMIT)
        .all()
    )
    return [
        {"score": score, "at": created_at.isoformat() if created_at else None}
        for score, created_at in rows
    ]


@router.get("/network/privacy-score")
async def get_network_privacy_score(
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    enabled = _is_windscribe_enabled(db)
    snapshot = _latest_snapshot(db) if enabled else None
    if snapshot is None:
        return {
            "enabled": enabled,
            "score": None,
            "grade": None,
            "deductions": [],
            "checks": [],
            "checked_at": None,
            "history": [],
        }
    return {
        "enabled": True,
        "score": snapshot.score,
        "grade": snapshot.grade,
        "deductions": snapshot.deductions or [],
        "checks": snapshot.checks or [],
        "checked_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "history": _score_history(db),
    }


@router.get("/network/privacy-score/history")
async def get_network_privacy_score_history(
    days: int = 30,
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    if not _is_windscribe_enabled(db):
        return {"days": []}

    clamped_days = min(days, _SCORE_HISTORY_DAYS_MAX)
    cutoff = utcnow() - timedelta(days=clamped_days)
    rows = (
        db.query(NetworkPrivacySnapshot)
        .filter(NetworkPrivacySnapshot.created_at >= cutoff)
        .order_by(NetworkPrivacySnapshot.id.asc())
        .all()
    )

    by_date: dict[str, NetworkPrivacySnapshot] = {}
    for row in rows:
        by_date[row.created_at.date().isoformat()] = row

    result_days = []
    for date, row in sorted(by_date.items()):
        severities = Counter(d.get("severity") for d in (row.deductions or []))
        result_days.append(
            {
                "date": date,
                "score": row.score,
                "critical_count": severities.get("critical", 0),
                "warning_count": severities.get("warning", 0),
                "info_count": severities.get("info", 0),
            }
        )
    return {"days": result_days}


def _derive_alert_status(checks: list[dict]) -> str:
    statuses = {check.get("status") for check in checks}
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    if statuses & {"ok", "info"}:
        return "safe"
    return "unknown"


@router.get("/network/threat-alerts")
async def get_network_threat_alerts(
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    enabled = _is_windscribe_enabled(db)
    snapshot = _latest_snapshot(db) if enabled else None
    if snapshot is None:
        return {"enabled": enabled, "status": "unknown", "alerts": []}
    checks = snapshot.checks or []
    alerts = [
        {
            "check_id": check["check_id"],
            "severity": check["status"],
            "detail": check.get("evidence", ""),
            "detected_at": check.get("detected_at"),
        }
        for check in checks
        if check.get("status") in ("warning", "critical")
    ]
    return {"enabled": True, "status": _derive_alert_status(checks), "alerts": alerts}


@router.get("/devices/{hardware_id}/threat-profile")
async def get_device_threat_profile(
    hardware_id: int,
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    hardware = db.get(Hardware, hardware_id)
    if hardware is None:
        raise HTTPException(status_code=404, detail="Hardware not found")
    return {
        "hardware_id": hardware_id,
        "score": hardware.privacy_score,
        "deductions": hardware.threat_profile or [],
    }


@router.get("/network/attack-surface")
async def get_attack_surface(
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    devices = db.query(Hardware).filter(Hardware.is_placeholder.is_(False)).all()
    results = []

    for hw in devices:
        scan_result = (
            db.query(ScanResult)
            .filter(
                ScanResult.matched_entity_type == "hardware",
                ScanResult.matched_entity_id == hw.id,
            )
            .order_by(ScanResult.id.desc())
            .first()
        )
        if scan_result is None and hw.source_scan_result_id:
            scan_result = db.get(ScanResult, hw.source_scan_result_id)

        if scan_result and scan_result.open_ports_json:
            try:
                ports_data = scan_result.open_ports_json
                if ports_data:
                    results.append(
                        {
                            "hardware_id": hw.id,
                            "name": hw.name,
                            "ip_address": hw.ip_address,
                            "vendor_icon_slug": hw.vendor_icon_slug,
                            "custom_icon": hw.custom_icon,
                            "ports": ports_data,
                        }
                    )
            except Exception:
                pass

    return {"attack_surface": results}
