"""SRV-02: the process topology is explicit, and an ambiguous one is refused.

`CB_RUN_INPROCESS_WORKERS` alone could not express the deployment: an API
process left on its default while dedicated worker containers ran the same
loops produced two notification workers, two discovery workers and two ingest
loops, and nothing anywhere said so. The mode names the topology, the legacy
flag keeps working, and a combination that describes two different topologies
fails at startup instead of being resolved by whichever branch reads its
variable first.
"""

from __future__ import annotations

import pytest

from app.core.topology import (
    INPROCESS_WORKER_FUNCTIONS,
    JOB_OWNERS,
    TopologyConfigError,
    TopologyMode,
    api_runs_inprocess_workers,
    describe,
    owner_of,
    resolve_mode,
)


def test_the_default_is_the_single_appliance():
    """An existing single-process install sets nothing and must not change."""
    assert resolve_mode(env={}) is TopologyMode.MONO
    assert api_runs_inprocess_workers(TopologyMode.MONO) is True


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"CB_TOPOLOGY_MODE": "mono"}, TopologyMode.MONO),
        ({"CB_TOPOLOGY_MODE": "api"}, TopologyMode.API),
        ({"CB_TOPOLOGY_MODE": "worker"}, TopologyMode.WORKER),
        # The legacy spelling still decides when the mode is unset.
        ({"CB_RUN_INPROCESS_WORKERS": "false"}, TopologyMode.API),
        ({"CB_RUN_INPROCESS_WORKERS": "true"}, TopologyMode.MONO),
        # Agreeing settings are not a conflict.
        ({"CB_TOPOLOGY_MODE": "api", "CB_RUN_INPROCESS_WORKERS": "false"}, TopologyMode.API),
        ({"CB_TOPOLOGY_MODE": "mono", "CB_RUN_INPROCESS_WORKERS": "true"}, TopologyMode.MONO),
    ],
)
def test_modes_resolve(env, expected):
    assert resolve_mode(env=env) is expected


@pytest.mark.parametrize(
    "env",
    [
        {"CB_TOPOLOGY_MODE": "api", "CB_RUN_INPROCESS_WORKERS": "true"},
        {"CB_TOPOLOGY_MODE": "worker", "CB_RUN_INPROCESS_WORKERS": "true"},
        {"CB_TOPOLOGY_MODE": "mono", "CB_RUN_INPROCESS_WORKERS": "false"},
    ],
)
def test_a_contradictory_topology_is_refused(env):
    """This is the mixed-mode configuration that duplicated work. It has to be
    a startup failure: a duplicated notification is not visible in a log line
    the operator never reads."""
    with pytest.raises(TopologyConfigError) as excinfo:
        resolve_mode(env=env)
    message = str(excinfo.value)
    assert "CB_TOPOLOGY_MODE" in message and "CB_RUN_INPROCESS_WORKERS" in message


def test_an_unknown_mode_is_refused():
    with pytest.raises(TopologyConfigError, match="not a known topology mode"):
        resolve_mode(env={"CB_TOPOLOGY_MODE": "dedicated"})


def test_api_only_mode_starts_no_inprocess_worker():
    assert api_runs_inprocess_workers(TopologyMode.API) is False
    assert api_runs_inprocess_workers(TopologyMode.WORKER) is False
    assert describe(TopologyMode.API)["inprocess_functions"] == []


def test_every_inprocess_function_has_a_declared_owner():
    """SRV-02's inventory clause: no background function may be undeclared."""
    for function in INPROCESS_WORKER_FUNCTIONS:
        assert owner_of(function) in {"api", "worker"}


def test_an_undeclared_function_is_an_error_rather_than_a_default():
    with pytest.raises(TopologyConfigError, match="no declared owner"):
        owner_of("something_nobody_wrote_down")


def test_the_dedicated_worker_types_are_all_owned_by_a_worker():
    """The types `app.workers.main --type` can start must not also be claimed
    by the API process, or both would run them."""
    from app.workers.main import _TYPE_MAP

    aliases = {
        "discovery": "discovery",
        "notification": "notifications",
        "telemetry": "telemetry_ingest",
        "monitor_scheduler": "monitor_scheduler",
        "monitor_poll": "monitor_poll",
        "monitor_probe_dispatch": "monitor_probe_dispatch",
    }
    for worker_type in set(_TYPE_MAP.values()):
        function = aliases[worker_type]
        assert JOB_OWNERS[function] == "worker", f"{function} is not owned by a worker process"


def test_a_dedicated_worker_announces_its_ownership(caplog, monkeypatch):
    """A worker that cannot say which topology it is part of leaves the
    duplicate-owner question unanswerable from the logs."""
    import logging

    from app.workers.main import _log_topology

    monkeypatch.setenv("CB_TOPOLOGY_MODE", "worker")
    monkeypatch.delenv("CB_RUN_INPROCESS_WORKERS", raising=False)
    with caplog.at_level(logging.INFO, logger="app.workers.main"):
        _log_topology("notification")

    assert any("mode=worker" in record.getMessage() for record in caplog.records)


def test_a_dedicated_worker_warns_when_the_api_also_claims_it(caplog, monkeypatch):
    """The mixed-mode case: mono says the API owns the background functions,
    yet a dedicated worker for one of them is starting."""
    import logging

    from app.workers.main import _log_topology

    monkeypatch.setenv("CB_TOPOLOGY_MODE", "mono")
    monkeypatch.delenv("CB_RUN_INPROCESS_WORKERS", raising=False)
    with caplog.at_level(logging.INFO, logger="app.workers.main"):
        _log_topology("notification")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "a dedicated worker under CB_TOPOLOGY_MODE=mono warned about nothing"
    assert "CB_TOPOLOGY_MODE=api" in warnings[0].getMessage()


def test_a_contradiction_is_reported_rather_than_crashing_the_worker(caplog, monkeypatch):
    """The worker's job is to run; a configuration contradiction is reported at
    error level, not raised into a container restart loop."""
    import logging

    from app.workers.main import _log_topology

    monkeypatch.setenv("CB_TOPOLOGY_MODE", "api")
    monkeypatch.setenv("CB_RUN_INPROCESS_WORKERS", "true")
    with caplog.at_level(logging.INFO, logger="app.workers.main"):
        _log_topology("notification")

    assert [r for r in caplog.records if r.levelno == logging.ERROR]


async def test_the_api_refuses_to_start_on_a_contradictory_topology(monkeypatch):
    """The refusal has to happen at startup. A process that boots on an
    ambiguous topology has already begun duplicating whatever it duplicates,
    and the operator finds out from the effects."""
    from app.core.server_state import get_state, set_state
    from app.main import app

    monkeypatch.setenv("CB_TOPOLOGY_MODE", "api")
    monkeypatch.setenv("CB_RUN_INPROCESS_WORKERS", "true")
    # The lifecycle state is a process-global singleton and the failed startup
    # leaves it on STARTING; restoring it keeps this test from deciding the
    # outcome of whatever runs next in the session.
    previous_state = get_state()
    try:
        with pytest.raises(SystemExit):
            async with app.router.lifespan_context(app):
                pass
    finally:
        set_state(previous_state)
