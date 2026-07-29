from datetime import timedelta

from app.core.time import utcnow
from app.services import agent_registry as svc


def test_expires_pending_agents_older_than_seven_days(db_session, factories):
    stale = factories.agent(status="pending", enrolled_at=utcnow() - timedelta(days=8))
    fresh = factories.agent(status="pending", enrolled_at=utcnow() - timedelta(days=1))

    count = svc.expire_stale_pending_agents(db_session)

    assert count == 1
    db_session.refresh(stale)
    db_session.refresh(fresh)
    assert stale.status == "rejected"
    assert fresh.status == "pending"
