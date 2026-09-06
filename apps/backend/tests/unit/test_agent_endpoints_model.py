"""agent_endpoints stores the operator's declared agent-facing addresses."""

from __future__ import annotations

from app.db.models import AppSettings


def test_agent_endpoints_defaults_to_empty_list(db_session):
    row = AppSettings(id=1)
    db_session.add(row)
    db_session.flush()
    assert row.agent_endpoints == []


def test_agent_endpoints_round_trips_a_list_of_objects(db_session):
    row = AppSettings(id=1, agent_endpoints=[{"id": "a1b2c3", "label": "LAN", "url": "https://10.0.0.5"}])
    db_session.add(row)
    db_session.flush()
    db_session.expire(row)
    assert row.agent_endpoints[0]["label"] == "LAN"


def test_agent_records_the_endpoint_it_dialed(db_session, factories):
    agent = factories.agent(enrolled_via_endpoint="https://cb.example.com")
    db_session.flush()
    assert agent.enrolled_via_endpoint == "https://cb.example.com"


def test_enrolled_via_endpoint_is_optional_for_agents_from_before_this_feature(
    db_session, factories
):
    agent = factories.agent()
    db_session.flush()
    assert agent.enrolled_via_endpoint is None
