import logging

from sqlalchemy.orm import Session

from app.db.models import Hardware, PrivacyScoreHistory
from app.services.windscribe_intel import intel_client

logger = logging.getLogger(__name__)


def calculate_privacy_score(hardware: Hardware, threat_feed: dict) -> tuple[int, list[str]]:
    """Ruleset engine that evaluates hardware discovery data against intelligence feeds."""
    score = 100
    profile = []

    if hardware.status == "down":
        score -= 5
        profile.append("Offline (No Telemetry)")

    # Example logic using the threat feed mock
    if hardware.mac_address:
        # Dummy penalty
        score -= 10
        profile.append("MAC Visible to Network")

    return max(0, score), profile


async def evaluate_hardware_privacy(db: Session, hardware_id: int) -> dict | None:
    hardware = db.query(Hardware).filter(Hardware.id == hardware_id).first()
    if not hardware:
        return None

    threat_feed = await intel_client.fetch_threat_feed()
    score, profile = calculate_privacy_score(hardware, threat_feed)

    hardware.privacy_score = score
    hardware.threat_profile = profile

    history_entry = PrivacyScoreHistory(
        hardware_id=hardware.id, score=score, threat_profile=profile
    )
    db.add(history_entry)
    db.commit()
    return {"score": score, "threat_profile": profile}
