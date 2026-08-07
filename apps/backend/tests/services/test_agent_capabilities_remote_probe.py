"""`remote_probe`'s real configuration schema (Task 5, design §3).

The placeholder these replace accepted no key at all, so nothing anywhere could
carry a concurrency limit or a scope override. Half of what is pinned here is
therefore the *upgrade* path: every already-approved agent holds `config = {}`
in `agent_capability_grants` and no migration may backfill it, so the new
defaults have to reach those agents through the read-time merge in
`_structured_grant` or the design's "no manual scope entry required" promise
quietly excludes every agent approved before this commit.

The CIDR and hostname rules themselves live in `core/agent_scope.py` and are
tested by `tests/unit/test_agent_scope.py`; what matters here is that the
capability normalizer delegates to them rather than growing a second rule set.
"""

from __future__ import annotations

import pytest

from app.db.models import AgentCapabilityGrant
from app.services import agent_registry as svc
from app.services.agent_capabilities import (
    CAPABILITY_DEFINITIONS,
    default_config_for,
    normalize_grant,
)

_DESIGN_DEFAULTS = {
    "max_concurrent": 20,
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "additional_hostnames": [],
}


def _config(**overrides: object) -> dict[str, object]:
    """A grant as the wire carries it, with `config` overridden per test."""
    return {"enabled": True, "config": dict(overrides)}


def test_defaults_match_the_design_document() -> None:
    assert default_config_for("remote_probe") == _DESIGN_DEFAULTS
    # Granted-but-idle stays the design (D-10): the default grant executes
    # nothing until a monitor names this agent as its vantage.
    assert CAPABILITY_DEFINITIONS["remote_probe"].default_enabled is True

    # The registry hands out its own list objects on every read, or one caller
    # appending a CIDR to the scope it was given would widen every future
    # agent's defaults for the life of the process.
    default_config_for("remote_probe")["additional_cidrs"].append("10.0.0.0/24")
    assert default_config_for("remote_probe") == _DESIGN_DEFAULTS


def test_max_concurrent_out_of_range_raises() -> None:
    for limit in (1, 20, 100):
        _, config = normalize_grant("remote_probe", _config(max_concurrent=limit))
        assert config["max_concurrent"] == limit

    for limit in (0, -1, 101, 1000):
        with pytest.raises(ValueError, match="between 1 and 100"):
            normalize_grant("remote_probe", _config(max_concurrent=limit))

    # `True` is an `int` in Python and would otherwise sail through as 1.
    for wrong_type in (True, "20", 20.0, None):
        with pytest.raises(ValueError, match="between 1 and 100"):
            normalize_grant("remote_probe", _config(max_concurrent=wrong_type))


def test_unknown_key_raises() -> None:
    with pytest.raises(ValueError, match="unknown remote probe settings: scope, timeout_s"):
        normalize_grant("remote_probe", _config(timeout_s=5, scope=[]))

    # The nearest-miss spelling matters most: a config named `cidrs` would be
    # silently persisted and shipped to an agent that derives nothing from it.
    with pytest.raises(ValueError, match="unknown remote probe settings: cidrs"):
        normalize_grant("remote_probe", _config(cidrs=["10.0.0.0/24"]))


def test_normalize_remote_probe_config_rejects_default_routes() -> None:
    """§3, via `core.agent_scope.normalize_scope_cidr` — the capability layer
    owns no CIDR rule of its own, it only names the field that failed."""
    for field in ("additional_cidrs", "excluded_cidrs"):
        for default_route in ("0.0.0.0/0", "::/0"):
            with pytest.raises(ValueError, match="whole address space"):
                normalize_grant("remote_probe", _config(**{field: [default_route]}))

    _, config = normalize_grant(
        "remote_probe",
        _config(
            additional_cidrs=["10.9.0.7/24", "10.9.0.0/24"],
            excluded_cidrs=["192.168.4.0/24"],
            additional_hostnames=["NAS.Lan.", "*.branch.example.com"],
        ),
    )
    assert config["additional_cidrs"] == ["10.9.0.0/24"]
    assert config["excluded_cidrs"] == ["192.168.4.0/24"]
    assert config["additional_hostnames"] == ["*.branch.example.com", "nas.lan"]

    # Every wrong *type* has to reach the 422 as a `ValueError` too. A
    # `TypeError` escaping here is a 500 on an admin route, because
    # `schemas/agents.py::_validate_capability_map` catches only `ValueError`.
    for wrong_type in ("10.0.0.0/24", 5, None, {"10.0.0.0/24": True}):
        with pytest.raises(ValueError, match="additional_cidrs must be a list"):
            normalize_grant("remote_probe", _config(additional_cidrs=wrong_type))
        with pytest.raises(ValueError, match="excluded_cidrs must be a list"):
            normalize_grant("remote_probe", _config(excluded_cidrs=wrong_type))
        with pytest.raises(ValueError, match="additional_hostnames must be a list"):
            normalize_grant("remote_probe", _config(additional_hostnames=wrong_type))
    with pytest.raises(ValueError, match="additional_hostnames"):
        normalize_grant("remote_probe", _config(additional_hostnames=["10.0.0.9"]))
    for wrong_mode in ("anything_routable", [], 3, None):
        with pytest.raises(ValueError, match="scope_mode"):
            normalize_grant("remote_probe", _config(scope_mode=wrong_mode))


def test_bare_boolean_grant_acquires_the_default_config(db_session, factories) -> None:
    """`{"remote_probe": true}` is the shape the approval modal and every
    existing test send; `normalize_grant` is the single place it picks up a
    config, so the wire form never has to learn about the new keys."""
    assert normalize_grant("remote_probe", True) == (True, _DESIGN_DEFAULTS)
    assert normalize_grant("remote_probe", False) == (False, _DESIGN_DEFAULTS)

    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")
    svc.approve_agent(
        db_session,
        agent.id,
        approving_user_id=admin.id,
        capability_overrides={"remote_probe": True},
    )

    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="remote_probe")
        .one()
    )
    assert grant.config == _DESIGN_DEFAULTS


def test_existing_grant_with_empty_config_reads_back_the_defaults(db_session, factories) -> None:
    """The row an agent approved before this commit carries: `config = {}`.
    `_structured_grant` merges the registry defaults over it at read time, so
    that agent is dispatchable with the documented concurrency and a derived
    scope without anyone re-approving it."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True, config={})
    db_session.flush()

    structured = svc.structured_grants_dict(db_session, agent.id)
    assert structured["remote_probe"] == {"enabled": True, "config": _DESIGN_DEFAULTS}
    assert (
        svc.bulk_structured_grants_dict(db_session, [agent.id])[agent.id]["remote_probe"]
        == structured["remote_probe"]
    )

    # A partial config keeps its own value and inherits the rest — the same
    # merge that lets a future key be added without touching stored rows.
    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="remote_probe")
        .one()
    )
    grant.config = {"max_concurrent": 4}
    db_session.flush()
    assert svc.structured_grants_dict(db_session, agent.id)["remote_probe"]["config"] == {
        **_DESIGN_DEFAULTS,
        "max_concurrent": 4,
    }


def test_new_registry_config_is_not_backfilled_onto_already_approved_agents(
    db_session, factories
) -> None:
    """Global Constraint: "Never backfill grant rows in a migration." Reading
    the merged defaults must not write them, or the stored row stops being
    distinguishable from an administrator who pinned those exact values and a
    later default change would silently not reach it."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="remote_probe", enabled=True, config={})
    db_session.flush()

    svc.structured_grants_dict(db_session, agent.id)
    svc.bulk_structured_grants_dict(db_session, [agent.id])
    db_session.expire_all()

    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="remote_probe")
        .one()
    )
    assert grant.config == {}
