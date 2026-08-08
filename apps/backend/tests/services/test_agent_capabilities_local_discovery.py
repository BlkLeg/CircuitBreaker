"""`local_discovery`'s real configuration schema (Slice 4 Task 3, plan §1).

The placeholder these replace (`default_config={}` /
`_reject_unknown_keys("local_discovery")`) turned *every* key in the plan's
grant into a 422, so nothing anywhere could carry a port set, a job ceiling, or
a scope override. As with `remote_probe` in Slice 3, half of what is pinned
here is the upgrade path: an agent approved before this commit holds
`config = {}` in `agent_capability_grants` and no migration may backfill it, so
the defaults have to reach it through the read-time merge in `_structured_grant`
or plan §10's "no CIDR entry, no agent-side configuration" promise silently
excludes every already-enrolled agent.

The CIDR rules themselves live in `core/agent_scope.py` and are tested by
`tests/unit/test_agent_scope.py`. What matters here is that the normalizer
*delegates* to them rather than growing a second rule set — an administrator
must not be able to save a scope entry the dispatcher would later read
differently.
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

# plans/2026-08-04-cbi-agent-slice4-local-discovery.md §1, verbatim.
_PLAN_DEFAULTS = {
    "scope_mode": "direct_private",
    "excluded_cidrs": [],
    "additional_cidrs": [],
    "max_addresses_per_job": 1024,
    "max_concurrent_hosts": 64,
    "tcp_ports": [22, 53, 80, 443, 445, 3389, 8000, 8080, 8443],
    "host_timeout_ms": 1500,
    "job_timeout_seconds": 300,
    "auto_discovery_paused": False,
}


def _config(**overrides: object) -> dict[str, object]:
    """A grant as the wire carries it, with `config` overridden per test."""
    return {"enabled": True, "config": dict(overrides)}


def test_defaults_match_the_plan_document() -> None:
    assert default_config_for("local_discovery") == _PLAN_DEFAULTS
    # Plan §7: local discovery is on after normal approval, bounded by the
    # derived `direct_private` scope, and the approver keeps an explicit opt-out.
    assert CAPABILITY_DEFINITIONS["local_discovery"].default_enabled is True

    # The registry hands out its own list objects on every read, or one caller
    # appending a port to the set it was given would widen every future agent's
    # defaults for the life of the process.
    default_config_for("local_discovery")["tcp_ports"].append(9999)
    default_config_for("local_discovery")["additional_cidrs"].append("10.0.0.0/24")
    assert default_config_for("local_discovery") == _PLAN_DEFAULTS


@pytest.mark.parametrize(
    ("key", "accepted", "rejected"),
    [
        ("max_addresses_per_job", (1, 1024, 4096), (0, -1, 4097, 100000)),
        ("max_concurrent_hosts", (1, 64, 256), (0, -1, 257, 10000)),
        ("host_timeout_ms", (100, 1500, 10000), (99, 0, -1, 10001)),
        ("job_timeout_seconds", (30, 300, 1800), (29, 0, -1, 1801)),
    ],
)
def test_numeric_bounds_are_enforced(key, accepted, rejected) -> None:
    """Server-side hard ceilings on top of the configurable values (plan §1).

    Oversized requests are *rejected*, not silently truncated: an operator who
    typed 100 000 addresses must find out here rather than discover later that
    the agent quietly scanned 4 096 of them.
    """
    for value in accepted:
        _, config = normalize_grant("local_discovery", _config(**{key: value}))
        assert config[key] == value

    for value in rejected:
        with pytest.raises(ValueError, match=key.replace("_", " ")):
            normalize_grant("local_discovery", _config(**{key: value}))


def test_booleans_are_not_accepted_as_numbers() -> None:
    """`True` is an `int` in Python and would sail through a bare range check as
    1, silently configuring a one-address, one-host scan."""
    for key in ("max_addresses_per_job", "max_concurrent_hosts", "host_timeout_ms"):
        with pytest.raises(ValueError):
            normalize_grant("local_discovery", _config(**{key: True}))


def test_tcp_ports_are_bounded_deduplicated_and_ordered() -> None:
    _, config = normalize_grant("local_discovery", _config(tcp_ports=[443, 22, 443, 80]))
    assert config["tcp_ports"] == [22, 80, 443]

    _, config = normalize_grant("local_discovery", _config(tcp_ports=[]))
    assert config["tcp_ports"] == []

    for ports in ([0], [65536], [-1], ["80"], [True], list(range(1, 40))):
        with pytest.raises(ValueError, match="tcp ports"):
            normalize_grant("local_discovery", _config(tcp_ports=ports))

    with pytest.raises(ValueError, match="tcp ports"):
        normalize_grant("local_discovery", _config(tcp_ports="80,443"))


def test_scope_entries_are_delegated_to_the_shared_evaluator() -> None:
    """Not merely "a CIDR list is accepted" — the *same* normalizer the
    dispatcher and the Go agent evaluate against, so "the backend approved it"
    keeps implying "the agent will accept it"."""
    _, config = normalize_grant(
        "local_discovery",
        _config(additional_cidrs=["10.0.0.0/24"], excluded_cidrs=["192.168.1.5/24"]),
    )
    assert config["additional_cidrs"] == ["10.0.0.0/24"]
    # strict=False canonicalization, exactly as `normalize_scope_cidr` does it.
    assert config["excluded_cidrs"] == ["192.168.1.0/24"]

    for field in ("additional_cidrs", "excluded_cidrs"):
        with pytest.raises(ValueError, match="whole address space"):
            normalize_grant("local_discovery", _config(**{field: ["0.0.0.0/0"]}))
        with pytest.raises(ValueError, match="not a valid CIDR"):
            normalize_grant("local_discovery", _config(**{field: ["nonsense"]}))
        with pytest.raises(ValueError, match="must be a list"):
            normalize_grant("local_discovery", _config(**{field: "10.0.0.0/24"}))


def test_unknown_scope_mode_raises() -> None:
    with pytest.raises(ValueError, match="scope_mode"):
        normalize_grant("local_discovery", _config(scope_mode="everything"))
    with pytest.raises(ValueError, match="scope_mode"):
        normalize_grant("local_discovery", _config(scope_mode=1))


def test_unknown_key_raises() -> None:
    """Plan §1's ports and limits are the whole vocabulary. A key nobody
    implements must not be persisted and shipped to an agent that has no idea
    what to do with it."""
    with pytest.raises(ValueError, match="unknown local discovery settings: snmp_community"):
        normalize_grant("local_discovery", _config(snmp_community="public"))
    # `remote_probe`'s keys are not `local_discovery`'s: discovery targets are
    # prefixes, never names, so an approved hostname here would look granted
    # while never matching anything.
    with pytest.raises(ValueError, match="additional_hostnames"):
        normalize_grant("local_discovery", _config(additional_hostnames=["nas.internal"]))


def test_bare_boolean_grant_acquires_the_default_config(db_session, factories) -> None:
    """`{"local_discovery": true}` is the shape the approval modal sends. That
    must still land the full plan-§1 grant, or a normally-approved agent holds a
    discovery capability with no port set and no ceilings."""
    assert normalize_grant("local_discovery", True) == (True, _PLAN_DEFAULTS)
    assert normalize_grant("local_discovery", False) == (False, _PLAN_DEFAULTS)

    agent = factories.agent(status="pending")
    admin = factories.user(role="admin")
    svc.approve_agent(
        db_session,
        agent.id,
        approving_user_id=admin.id,
        capability_overrides={"local_discovery": True},
    )

    grant = (
        db_session.query(AgentCapabilityGrant)
        .filter_by(agent_id=agent.id, capability="local_discovery")
        .one()
    )
    assert grant.config == _PLAN_DEFAULTS


def test_existing_grant_with_empty_config_reads_back_the_defaults(db_session, factories) -> None:
    """The upgrade path. An agent approved before this commit holds `config = {}`
    and no migration backfills it; the read-time merge in `_structured_grant` is
    what makes plan §10's zero-configuration promise true for it too."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(agent, capability="local_discovery", enabled=True, config={})
    db_session.flush()

    structured = svc.structured_grants_dict(db_session, agent.id)
    assert structured["local_discovery"] == {"enabled": True, "config": _PLAN_DEFAULTS}
    assert (
        svc.bulk_structured_grants_dict(db_session, [agent.id])[agent.id]["local_discovery"]
        == structured["local_discovery"]
    )


def test_a_stored_override_still_wins_over_the_defaults(db_session, factories) -> None:
    """A partial config keeps its own values and inherits the rest — the same
    merge that lets a future key be added without touching stored rows."""
    agent = factories.agent(status="active")
    factories.agent_capability_grant(
        agent,
        capability="local_discovery",
        enabled=True,
        config={"max_concurrent_hosts": 8, "excluded_cidrs": ["10.0.0.0/24"]},
    )
    db_session.flush()

    config = svc.structured_grants_dict(db_session, agent.id)["local_discovery"]["config"]
    assert config["max_concurrent_hosts"] == 8
    assert config["excluded_cidrs"] == ["10.0.0.0/24"]
    assert config["tcp_ports"] == _PLAN_DEFAULTS["tcp_ports"]


def test_auto_discovery_paused_is_a_boolean_and_defaults_off() -> None:
    """Plan §6's per-agent pause. It rides the grant config because that is
    already the per-agent settings store; it is a scheduling control, so the
    agent receives it and does nothing with it."""
    _, config = normalize_grant("local_discovery", _config(auto_discovery_paused=True))
    assert config["auto_discovery_paused"] is True

    for value in (1, "true", None, []):
        with pytest.raises(ValueError, match="auto_discovery_paused"):
            normalize_grant("local_discovery", _config(auto_discovery_paused=value))
