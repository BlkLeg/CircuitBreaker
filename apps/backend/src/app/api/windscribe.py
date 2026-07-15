from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import require_auth
from app.db.models import PrivacyScoreHistory
from app.db.session import get_db
from app.services.privacy_score import evaluate_hardware_privacy
from app.services.windscribe_intel import intel_client

router = APIRouter()


@router.get("/network/privacy-score")
async def get_network_privacy_score(
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    scores = (
        db.query(PrivacyScoreHistory.score)
        .order_by(PrivacyScoreHistory.evaluated_at.desc())
        .limit(100)
        .all()
    )
    if scores:
        avg = sum([s[0] for s in scores]) / len(scores)
    else:
        avg = 100

    return {"score": int(avg), "history": [s[0] for s in scores]}


@router.get("/network/threat-alerts")
async def get_network_threat_alerts(
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    threat_feed = await intel_client.fetch_threat_feed()
    return threat_feed


@router.get("/devices/{hardware_id}/threat-profile")
async def get_device_threat_profile(
    hardware_id: int,
    db: Session = Depends(get_db),
    user: Any = Depends(require_auth),
) -> dict[str, Any]:
    res = await evaluate_hardware_privacy(db, hardware_id)
    if not res:
        raise HTTPException(status_code=404, detail="Hardware not found")

    score, profile = res
    return {"hardware_id": hardware_id, "score": score, "profile": profile}
