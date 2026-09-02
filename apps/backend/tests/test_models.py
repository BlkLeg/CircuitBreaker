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


def test_tls_pin_rotation_columns_default_to_null(db_session):
    """A deployment that has never rotated its TLS trust must read as
    "no rotation", not as a half-configured one."""
    from app.services.settings_service import get_or_create_settings

    settings = get_or_create_settings(db_session)
    assert settings.agent_tls_pin_successor_mode is None
    assert settings.agent_tls_pin_successor is None
    assert settings.agent_tls_pin_rotation_started_at is None
    assert settings.agent_tls_pin_rotation_overlap_expires_at is None


def test_agent_tls_pin_convergence_columns_default_to_null(db_session, factories):
    agent = factories.agent()
    assert agent.tls_pin_current_pinned_at is None
    assert agent.tls_pin_successor_pinned_at is None
