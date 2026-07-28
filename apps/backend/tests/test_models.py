"""Model-level unit tests."""


def test_arp_prober_defaults_to_disabled(db_session):
    """New AppSettings rows must have arp_enabled=False."""
    from app.db.models import AppSettings

    settings = AppSettings(id=9999)
    db_session.add(settings)
    db_session.flush()
    assert settings.arp_enabled is False, (
        f"arp_enabled defaults to {settings.arp_enabled!r}; expected False"
    )


def test_agent_model_roundtrip(db_session, factories):
    agent = factories.agent(status="pending", hostname="box1")
    grant = factories.agent_capability_grant(agent, capability="host_telemetry", enabled=True)
    event = factories.agent_event(agent, event_type="enrolled")

    db_session.flush()

    assert agent.id is not None
    assert agent.status == "pending"
    assert grant.agent_id == agent.id
    assert event.agent_id == agent.id


def test_agent_capability_grant_unique_per_agent(db_session, factories):
    import pytest
    from sqlalchemy.exc import IntegrityError

    agent = factories.agent()
    factories.agent_capability_grant(agent, capability="host_telemetry")
    db_session.flush()

    factories.agent_capability_grant(agent, capability="host_telemetry")
    with pytest.raises(IntegrityError):
        db_session.flush()
