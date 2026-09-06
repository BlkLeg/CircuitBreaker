"""agent_endpoints stores the operator's declared agent-facing addresses."""

from __future__ import annotations

from app.services.settings_service import get_or_create_settings


def test_agent_endpoints_defaults_to_empty_list(db_session):
    """agent_endpoints reads back as an empty list when nothing has set it.

    `app_settings` id=1 is the application's settings singleton -- other
    suites in this run (e.g. test_install_agent_script_endpoint.py) commit a
    real row for it through their own SessionLocal(), so constructing a fresh
    AppSettings(id=1) here would collide with pk_app_settings whenever this
    test runs after one of them. Going through get_or_create_settings, the
    same entry point the application itself uses, gets the singleton whether
    or not it already exists, and still proves the same thing: absent any
    write to the column, agent_endpoints reads back as an empty list rather
    than NULL.
    """
    row = get_or_create_settings(db_session)
    assert row.agent_endpoints == []


def test_agent_endpoints_round_trips_a_list_of_objects(db_session):
    """A list of dicts written to agent_endpoints round-trips through the DB.

    See test_agent_endpoints_defaults_to_empty_list for why this fetches the
    singleton via get_or_create_settings instead of constructing
    AppSettings(id=1) directly.
    """
    row = get_or_create_settings(db_session)
    row.agent_endpoints = [{"id": "a1b2c3", "label": "LAN", "url": "https://10.0.0.5"}]
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
