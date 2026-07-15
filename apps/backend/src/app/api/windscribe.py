"""Privacy & threat endpoints — served from the latest snapshot, never computed
on request. Disabled/no-data states return 200 empty shapes, not errors."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_auth
from app.db.models import AppSettings, Hardware, NetworkPrivacySnapshot
from app.db.session import get_db

router = APIRouter()

_HISTORY_LIMIT = 30


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
