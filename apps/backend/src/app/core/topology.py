"""Which process owns which background function (SRV-02).

Before this module the answer was spread across an environment variable
(`CB_RUN_INPROCESS_WORKERS`), a `--type` argument to the worker entrypoint, and
whatever the deployment happened to compose. Two combinations of those were
silently wrong rather than rejected: an API process left on the default while
dedicated worker containers ran the same loops (two notification workers, two
discovery workers, two ingest loops), and a worker container whose type was
also being served in-process.

The topology mode makes the deployment state one thing:

* ``mono``   — one appliance process. The API also runs the background owners.
  This is what the mono container and a single-node native install run, and it
  is the default so an existing single-process deployment is unchanged.
* ``api``    — API only. Every background function belongs to a dedicated
  worker process; the API runs none of them.
* ``worker`` — a dedicated worker process, which serves no HTTP.

`CB_RUN_INPROCESS_WORKERS` is still honoured as the legacy spelling, and a
value that contradicts `CB_TOPOLOGY_MODE` is a startup error rather than a
silent winner — SRV-2's build sequence calls for refusing ambiguous
combinations, and "which of my two settings won" is not a question an operator
should have to answer from duplicated notifications.

Being the single owner of a *function* is not the same as being the only
process that runs it: two replicas can both be in ``mono`` mode. That case is
handled where the work executes, by `app.core.job_lock.single_owner`, and this
module is what decides whether the loop is started at all.
"""

from __future__ import annotations

import logging
import os
from enum import StrEnum

_logger = logging.getLogger(__name__)


class TopologyMode(StrEnum):
    MONO = "mono"
    API = "api"
    WORKER = "worker"


class TopologyConfigError(RuntimeError):
    """Raised when the configured process roles cannot be reconciled."""


#: Every background function this server runs, and the process role that owns
#: it. `worker` entries are the dedicated worker types in
#: `app.workers.main`; `api` entries run on the API process's scheduler (under
#: an advisory lock, so replicas do not duplicate them). In `mono` mode one
#: process holds both roles.
#:
#: This table is the inventory SRV-2 asks for: every loop and job, classified,
#: with nothing left implicit.
JOB_OWNERS: dict[str, str] = {
    # Dedicated worker processes
    "discovery": "worker",
    "notifications": "worker",
    "telemetry_ingest": "worker",
    "integrations": "worker",
    "monitor_scheduler": "worker",
    "monitor_poll": "worker",
    "monitor_probe_dispatch": "worker",
    # API-process scheduler (cron/interval jobs, all single-owner locked)
    "cleanup_retention": "api",
    "rollups": "api",
    "backups": "api",
    "agent_dispatch_reconcile": "api",
    "discovery_profile_crons": "api",
    "certificate_renewal": "api",
    "vault_rotation": "api",
    "update_check": "api",
}

#: The background loops the API process starts in-process when it owns them.
#: Named so the mono/api decision is auditable rather than a boolean buried in
#: the lifespan.
INPROCESS_WORKER_FUNCTIONS: tuple[str, ...] = (
    "notifications",
    "discovery",
    "telemetry_ingest",
    "integrations",
)

_ENV_MODE = "CB_TOPOLOGY_MODE"
_ENV_LEGACY_INPROCESS = "CB_RUN_INPROCESS_WORKERS"


def resolve_mode(*, env: dict[str, str] | None = None) -> TopologyMode:
    """The topology mode this process runs in.

    Raises `TopologyConfigError` when the explicit mode and the legacy flag
    disagree, or when the mode is not one this build knows.
    """
    source = os.environ if env is None else env
    raw_mode = (source.get(_ENV_MODE) or "").strip().lower()
    legacy_raw = (source.get(_ENV_LEGACY_INPROCESS) or "").strip().lower()
    legacy = legacy_raw in {"1", "true", "yes"} if legacy_raw else None

    if not raw_mode:
        if legacy is False:
            return TopologyMode.API
        return TopologyMode.MONO

    try:
        mode = TopologyMode(raw_mode)
    except ValueError as exc:
        raise TopologyConfigError(
            f"{_ENV_MODE}={raw_mode!r} is not a known topology mode; "
            f"expected one of {', '.join(m.value for m in TopologyMode)}"
        ) from exc

    if legacy is not None:
        expected = mode is TopologyMode.MONO
        if legacy is not expected:
            raise TopologyConfigError(
                f"{_ENV_MODE}={mode.value} and {_ENV_LEGACY_INPROCESS}={legacy_raw!r} "
                "describe different topologies. In 'mono' the API process owns the "
                "background workers; in 'api' and 'worker' it does not. Set one of "
                f"them, not both — {_ENV_LEGACY_INPROCESS} is the legacy spelling of "
                f"{_ENV_MODE}."
            )
    return mode


def api_runs_inprocess_workers(mode: TopologyMode | None = None) -> bool:
    """Does the API process own the in-process background loops?"""
    resolved = resolve_mode() if mode is None else mode
    return resolved is TopologyMode.MONO


def owner_of(function: str) -> str:
    """The process role that owns `function`."""
    try:
        return JOB_OWNERS[function]
    except KeyError as exc:
        raise TopologyConfigError(
            f"{function!r} has no declared owner; every background function must "
            "appear in app.core.topology.JOB_OWNERS"
        ) from exc


def describe(mode: TopologyMode | None = None) -> dict[str, object]:
    """The topology as this process understands it, for logs and diagnostics."""
    resolved = resolve_mode() if mode is None else mode
    return {
        "mode": resolved.value,
        "api_runs_inprocess_workers": api_runs_inprocess_workers(resolved),
        "inprocess_functions": list(INPROCESS_WORKER_FUNCTIONS)
        if api_runs_inprocess_workers(resolved)
        else [],
        "job_owners": dict(JOB_OWNERS),
    }
