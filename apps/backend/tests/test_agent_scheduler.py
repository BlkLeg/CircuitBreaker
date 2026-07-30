from app.core.scheduler import get_scheduler


def test_expire_pending_agents_job_registered(ws_client):
    """The startup function must register expire_stale_pending_agents with
    the scheduler — a unit test on the function alone (see
    tests/services/test_agent_registry_expiry.py) doesn't catch it being
    dropped from main.py's wiring, which is exactly what happened here."""
    job = get_scheduler().get_job("expire_pending_agents")
    assert job is not None
