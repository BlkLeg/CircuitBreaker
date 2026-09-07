"""Whether a discovery request may be created, scheduled or dispatched.

`discovery_eligibility` answers the question about the *agent* — is it active,
granted, ready, in scope. This module answers the two it deliberately leaves
open, and both are about the request rather than the agent:

* **Grant limits.** `max_addresses_per_job` and the granted `tcp_ports` set are
  properties of a particular request's size and shape. The refusal names the
  offending number, and the reason codes are the Go collector's own
  (`internal/collect/discover`), because the agent refuses the same request
  under the same code immediately before it runs — an operator must not see one
  word from the server and another from the agent for one condition.
* **Pause scopes.** Three holds can stop a scan: the fleet-wide
  `app_settings.agent_discovery_paused`, the per-agent
  `local_discovery.auto_discovery_paused` grant key, and the per-subnet
  `discovery_profiles.paused_at`. `profiles_due_for_scheduling` is the single
  place in the product that decides whether a profile gets a cron, so both
  registration sites — `startup.jobs` at boot and
  `core.scheduler.reload_discovery_jobs` on every profile write — ask it rather
  than writing the predicate themselves.

Split out of `discovery_service`, which is the scan engine. These checks run
before a scan exists and are consulted from four call sites that have nothing
to do with running one: profile save, ad hoc job creation, dispatch, and the
dispatcher's re-check of a queued job.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection, Coroutine, Iterator, Sequence
from typing import Any, cast

from sqlalchemy.orm import Session

from app.core import agent_scope
from app.db.models import DiscoveryProfile, ScanJob
from app.services import discovery_eligibility
from app.services.agent_capabilities import (
    _LOCAL_DISCOVERY_BOUNDS,
    _LOCAL_DISCOVERY_DEFAULT_CONFIG,
)
from app.services.discovery_network import _NMAP_OVERRIDE_PREFIX
from app.services.settings_service import get_or_create_settings

_logger = logging.getLogger(__name__)


# `scan_jobs.source_type` for a job an agent executes. It joins the existing
# manual|prober|scheduled|listener_triggered vocabulary (`db/models/discovery.py`) rather
# than replacing any of it: `triggered_by` still says *who* asked for the scan,
# and this says *where* it ran.
SOURCE_TYPE_AGENT = "agent"

# The two limits `discovery_eligibility` deliberately leaves to whoever holds the
# request. Both names are the Go collector's own — `internal/collect/discover`'s
# `ErrorCodeAddressLimit` and `ErrorCodePortNotGranted` — because the agent
# refuses the same request under the same code immediately before it runs, and an
# operator comparing a 422 with a job's `error_reason` must not have to translate
# between two spellings of one rule. Every other refusal reason comes from
# `discovery_eligibility`'s closed vocabulary rather than a second copy of it.
REASON_ADDRESS_LIMIT = "address_limit_exceeded"
REASON_PORT_NOT_GRANTED = "port_not_granted"

# The address ceiling to apply when the grant names none, and the hard cap on the
# one it does name. Read from `agent_capabilities` rather than restated so the
# validator, the agent's normalizer and the administrator-facing bounds cannot
# drift. Falling back to the *default* rather than the cap is the Go validator's
# own direction (`NewValidator`: "a grant that decoded to zeros must mean the
# documented bound, never no bound at all").
_DEFAULT_ADDRESS_CEILING = int(_LOCAL_DISCOVERY_DEFAULT_CONFIG["max_addresses_per_job"])
_MAX_ADDRESS_CEILING = _LOCAL_DISCOVERY_BOUNDS["max_addresses_per_job"][1]

# The only place a discovery request can name a TCP port set today: the `-p` spec
# inside `nmap_arguments`, which both the profile schema and the ad-hoc scan
# request carry. Plan §3 requires the port set to be "within configured and hard
# limits" at creation time, and an operator who typed a port their agent may
# never open has to find out here rather than have it silently dropped in favour
# of the grant's own list at dispatch. The character class matches
# `core.nmap_args._PORT_SPEC`, which is what already validated the token.
_PORT_SPEC_RE = re.compile(r"-p\s*([0-9,\-]+)")


class AgentExecutionLocationError(ValueError):
    """An agent-targeted profile or job the named agent may not run as written.

    A `ValueError` because that is the failure `create_scan_job` already reports
    with and what `api/discovery.py`'s ad-hoc arm already answers 422 to — though
    that arm replaces the message with a generic one today, so `reason` reaches a
    caller only through `discovery_profiles_service`, which raises the structured
    422 itself.

    `reason` is the machine-readable half — the frontend renders it and the
    dispatch audit trail records it — and `detail` is the specific that produced
    it (the agent status, the collector and its state, the scope decision and its
    prefix, the offending port, the count against the ceiling), which cannot be
    re-derived from the request afterwards.
    """

    def __init__(self, agent_id: int, reason: str, detail: str | None = None) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.detail = detail
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"agent {agent_id} may not run this discovery request: {reason}{suffix}")


def first_ungranted_tcp_port(nmap_arguments: str | None, granted: Collection[int]) -> int | None:
    """The first TCP port *nmap_arguments* asks for that the grant does not allow.

    Ranges are walked rather than expanded into a set: `-p 1-65535` names 65 535
    ports while a grant may list at most `agent_capabilities._MAX_TCP_PORTS` of
    them, so the walk cannot run longer than the granted set plus one before it
    finds its answer. An unparseable fragment is skipped — `core.nmap_args` is
    what refuses those, and refusing them twice here would report a syntax
    mistake as a capability violation.

    An empty *granted* collection grants no port at all, which is the Go
    validator's rule verbatim: a port outside the grant is a capability
    violation, not a missing default.
    """
    for port in _iter_requested_tcp_ports(nmap_arguments):
        if port not in granted:
            return port
    return None


def _iter_requested_tcp_ports(nmap_arguments: str | None) -> Iterator[int]:
    """Every port the `-p` spec names, in the order it names them.

    A generator rather than a set so `first_ungranted_tcp_port` can answer
    `-p 1-65535` without materializing 65 535 integers, which is the whole
    reason the walk exists in this shape.
    """
    match = _PORT_SPEC_RE.search(nmap_arguments or "")
    if match is None:
        return
    for part in match.group(1).split(","):
        low, _, high = part.partition("-")
        try:
            first = int(low)
            last = int(high) if high else first
        except ValueError:
            # An unparseable fragment is skipped — `core.nmap_args` is what
            # refuses those, and refusing them twice here would report a syntax
            # mistake as a capability violation.
            continue
        yield from range(first, last + 1)


def requested_tcp_ports(nmap_arguments: str | None, granted: Collection[int]) -> frozenset[int]:
    """The ports *nmap_arguments* names that the grant also allows.

    Intersected with *granted* rather than returned raw, so the answer is
    bounded by the grant's own `_MAX_TCP_PORTS` however wide the spec is. The
    dispatcher calls this only after `first_ungranted_tcp_port` has returned
    `None`, at which point the intersection is the request verbatim; the
    predicate is what keeps that true if the order is ever changed.

    An empty answer means the request named no ports of its own, which the
    dispatcher reads as "send the grant's list".
    """
    return frozenset(port for port in _iter_requested_tcp_ports(nmap_arguments) if port in granted)


def _granted_local_discovery_config(db: Session, agent_id: int) -> dict[str, Any]:
    """The agent's `local_discovery` grant config, registry defaults merged in.

    Imported lazily because `services/agent_discovery.py` imports this module:
    the ingest path and this one share one reader of the grant so they cannot
    disagree about an agent's ceilings, and that module is where the reader lives
    because it documents why the grant must be read through
    `structured_grants_dict` — an already-approved agent keeps `config = {}` in
    the database and resolves the registry defaults at render time.
    """
    from app.services.agent_discovery import discovery_grant_config

    return discovery_grant_config(db, agent_id)


def granted_address_ceiling(config: dict[str, Any]) -> int:
    """How many addresses one job may cover under *config*.

    A missing, non-integer or non-positive value means the documented default
    rather than "no limit"; `True` is an `int` and would otherwise configure a
    one-address scan.
    """
    raw = config.get("max_addresses_per_job")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return _DEFAULT_ADDRESS_CEILING
    return min(raw, _MAX_ADDRESS_CEILING)


def granted_tcp_ports(config: dict[str, Any]) -> frozenset[int]:
    """The ports *config* allows. A malformed list grants nothing (fail closed)."""
    ports = config.get("tcp_ports")
    if not isinstance(ports, (list, tuple)):
        return frozenset()
    return frozenset(p for p in ports if isinstance(p, int) and not isinstance(p, bool))


# ── Central pause controls (Slice 4 plan §3/§6, Task 25) ─────────────────────
#
# "The central UI can pause automatic discovery globally, per agent, or per
# subnet." Three switches, three storage locations, and — the part that decides
# the shape of the code below — no precedence between them: each one holds on its
# own and none of them releases either of the others. A single boolean derived by
# short-circuiting them together would read the same and behave the same until
# somebody resumed the wrong one.
#
# Pausing is not disabling. `DiscoveryProfile.enabled = 0` means the subnet is
# gone (plan §3 step 6) and is what a *disappearance* writes; a pause leaves the
# row, its cron expression, its jobs and its results exactly where they are and
# only withholds the APScheduler registration.

# The fleet-wide scope's storage is the mapped column
# `AppSettings.agent_discovery_paused`, named directly by its one reader
# (`global_agent_discovery_paused`) and its one writer (`POST
# /discovery/pause`). A `GLOBAL_DISCOVERY_PAUSE_SETTING = "agent_discovery_paused"`
# constant used to sit here; it is gone because nothing in `src/` ever read it,
# its stated justification (that both call sites named the scope through it) was
# false of both, and a constant-driven `setattr` type-checks against nothing —
# which is how the scope stayed unstorable behind six green tests until Fix A2.
# The per-agent key below is a different kind of name: it is a JSON key inside a
# grant blob, so no attribute lookup can ever check it for us.

#: The `local_discovery` grant key Task 3 added for the per-agent scope.
AGENT_DISCOVERY_PAUSE_KEY = "auto_discovery_paused"


def global_agent_discovery_paused(db: Session) -> bool:
    """Whether the fleet-wide hold is on.

    Scoped to **agent-executed** profiles by its callers, not to discovery as a
    whole: `app_settings.discovery_enabled` is already the product's master
    discovery switch, and a second flag that also silenced the server's own crons
    would mean an operator holding an agent fleet stopped scanning the networks
    the server can see itself.
    """
    settings = get_or_create_settings(db)
    # A direct attribute read, not `getattr(..., False)`: with the column in
    # place the fallback could only ever mask a mapping that had gone missing,
    # and it would mask it as "not paused" — the answer that quietly resumes a
    # fleet an operator believes is held.
    return bool(settings.agent_discovery_paused)


def paused_agent_ids(db: Session, agent_ids: Collection[int]) -> frozenset[int]:
    """Which of *agent_ids* carry `local_discovery.auto_discovery_paused`.

    Through `bulk_structured_grants_dict` so a fleet costs one query rather than
    one per profile, and so the registry defaults are merged the same way the
    single-agent reader merges them — an agent approved before Task 3 keeps
    `config = {}` in the database and resolves `auto_discovery_paused = False`
    at read time.
    """
    if not agent_ids:
        return frozenset()
    from app.services.agent_registry import bulk_structured_grants_dict

    grants = bulk_structured_grants_dict(db, sorted(set(agent_ids)))
    held = set()
    for agent_id, capabilities in grants.items():
        config = (capabilities.get(discovery_eligibility.CAPABILITY) or {}).get("config") or {}
        # `is True` and not truthiness: the normalizer stores a real boolean
        # (Task 3), and a stray string would otherwise pause an agent's
        # discovery indefinitely whichever word it held.
        if config.get(AGENT_DISCOVERY_PAUSE_KEY) is True:
            held.add(agent_id)
    return frozenset(held)


def agent_scheduling_paused(db: Session, agent_id: int) -> bool:
    """The two scopes that hold a whole agent, for a caller that has just one.

    The per-subnet scope is deliberately absent: a caller with one agent id has
    no profile to ask about yet. `discovery_bootstrap` is the caller — plan §3
    step 4's initial scan is scheduling like any other, so a paused agent gets
    its profile (nothing is deleted, and the subnet keeps its identity and its
    history) and no scan.
    """
    return global_agent_discovery_paused(db) or agent_id in paused_agent_ids(db, (agent_id,))


def _held_by_any_scope(
    profile: DiscoveryProfile, *, fleet_paused: bool, held_agents: Collection[int]
) -> bool:
    """The one definition of "this profile is held", given the two fleet answers.

    Both readers below call this rather than repeating the shape: one asks about
    every profile at once for the two registration sites, the other asks about a
    single profile when its cron fires, and a hold that reached one and not the
    other is precisely the class of defect this whole seam has produced twice.

    No precedence between the scopes, in either direction — each holds on its own
    and none of them releases either of the others.
    """
    if profile.paused_at is not None:
        return True
    if profile.scan_agent_id is None:
        # The fleet-wide and per-agent scopes are holds on *agent-executed*
        # discovery; the server's own crons answer to `discovery_enabled`.
        return False
    return fleet_paused or profile.scan_agent_id in held_agents


def profiles_due_for_scheduling(db: Session) -> list[DiscoveryProfile]:
    """The profiles a cron may be registered for.

    The single place that decides, asked by both registration sites —
    `core.scheduler.reload_discovery_jobs` on every write that can change a
    schedule, and `app.startup.scheduler.register_discovery_profile_crons` at process start.

    Lives here rather than in `core/scheduler.py` because which profiles are due
    is a discovery-domain question — the scheduler module's job is to turn the
    answer into `CronTrigger`s. A profile withheld here keeps everything it has
    except its next fire time, which is what `DiscoveryStatusOut.next_scheduled`
    then stops reporting.
    """
    profiles = (
        db.query(DiscoveryProfile)
        .filter(
            DiscoveryProfile.enabled == 1,
            DiscoveryProfile.schedule_cron.isnot(None),
            DiscoveryProfile.schedule_cron != "",
        )
        .all()
    )
    agent_ids = {p.scan_agent_id for p in profiles if p.scan_agent_id is not None}
    # Both fleet-wide reads are skipped entirely when no profile names an agent,
    # so an installation with no agents pays nothing for this gate.
    fleet_paused = bool(agent_ids) and global_agent_discovery_paused(db)
    held_agents = paused_agent_ids(db, agent_ids)
    return [
        profile
        for profile in profiles
        if not _held_by_any_scope(profile, fleet_paused=fleet_paused, held_agents=held_agents)
    ]


def profile_scheduling_held(db: Session, profile: DiscoveryProfile) -> bool:
    """Whether *profile* may not scan **right now**, across all three scopes.

    The fire-time half of the gate, and the reason the pause is a property of the
    database rather than of one process's scheduler state. APScheduler is
    process-local and production runs `uvicorn --workers 2`, so a pause applied
    through an API request rebuilds only the schedule of the worker that served
    it; the other worker's registered cron keeps its fire times, and nothing ever
    rebuilds that worker's schedule on its own. Registration-time gating alone is
    therefore a hold on one worker, not on the fleet.

    Costs at most two small queries, on a path whose next step is a network scan.
    """
    agent_id = profile.scan_agent_id
    if profile.paused_at is not None or agent_id is None:
        # Neither fleet-wide read can change the answer for a profile already
        # held on its own row or with no agent to hold, so neither is paid for.
        return _held_by_any_scope(profile, fleet_paused=False, held_agents=())
    return _held_by_any_scope(
        profile,
        fleet_paused=global_agent_discovery_paused(db),
        held_agents=paused_agent_ids(db, (agent_id,)),
    )


def _eligibility_now(
    pending: Coroutine[Any, Any, discovery_eligibility.Eligibility],
) -> discovery_eligibility.Eligibility:
    """Resolve an eligibility coroutine that cannot suspend, from sync code.

    `evaluate_eligibility` is `async` for exactly one reason: its `require_online`
    branch awaits agent presence in Redis. Creation-time validation passes
    `require_online=False` (D-5 — an offline agent parks its job as
    `waiting_for_agent`, so reachability is a scheduling condition and not a
    configuration error), so the coroutine runs to its return without ever
    suspending and one step yields the answer.

    Neither of the two callers can use `asyncio.run`: `POST /discovery/profiles`
    is a sync endpoint on a worker thread with no loop, while `create_scan_job`
    is reached from coroutines that are already on one. A thread hop would be the
    other option and would hand this transaction's connection to a second thread.

    If a future edit adds a suspension point ahead of the checks, this raises
    instead of quietly skipping validation.
    """
    try:
        pending.send(None)
    except StopIteration as done:
        return cast(discovery_eligibility.Eligibility, done.value)
    finally:
        pending.close()
    raise RuntimeError(
        "discovery eligibility suspended during creation-time validation; "
        "it must be resolved on an event loop"
    )


def validate_agent_execution_location(
    db: Session,
    *,
    scan_agent_id: int | None,
    targets: Sequence[str],
    nmap_arguments: str | None = None,
    tenant_id: int | None = None,
) -> None:
    """Refuse an agent-targeted profile or job the agent may not run (plan §3).

    `scan_agent_id is None` is the existing server discovery engine — every
    profile and job that predates Slice 4 — and is returned on untouched.

    This is the *configuration* checkpoint plan §7 names first, asked at both of
    the moments plan §3 requires it: profile save and job creation.
    It runs in addition to the dispatch-time re-check and never instead of it: an
    agent's scope is derived from what it reports about its own interfaces, so it
    can change between a profile save and the job that profile eventually
    produces, which is the whole reason the grant carries a version.

    Order matters, and it is the Go validator's order:

    1. The agent and the targets, through `discovery_eligibility` — the one
       module that answers this at all four checkpoints, so a UI that learned
       `agent_inactive` here reads the same string off the dispatch audit row.
    2. The requested ports against the grant.
    3. The address count **last**, because `agent_scope.address_count` skips an
       unparseable prefix rather than refusing it: counting before scope has
       judged every target would let a malformed one slip under the ceiling.
    """
    if scan_agent_id is None:
        return

    decision = _eligibility_now(
        discovery_eligibility.evaluate_eligibility(
            db,
            scan_agent_id,
            targets=tuple(targets),
            # No discovery row carries a tenant yet — `ScanJob.tenant_id` is
            # stamped from the agent when the job is routed (D-17) — and
            # `evaluate_eligibility` reads `None` as a tenant-less request, which
            # is legal on a tenant-scoped agent because the target is still
            # bounded by that agent's own networks.
            tenant_id=tenant_id,
            require_online=False,
        )
    )
    if not decision.ok:
        raise AgentExecutionLocationError(scan_agent_id, decision.reason or "", decision.detail)

    config = _granted_local_discovery_config(db, scan_agent_id)
    ungranted_port = first_ungranted_tcp_port(nmap_arguments, granted_tcp_ports(config))
    if ungranted_port is not None:
        raise AgentExecutionLocationError(
            scan_agent_id, REASON_PORT_NOT_GRANTED, str(ungranted_port)
        )

    ceiling = granted_address_ceiling(config)
    count = agent_scope.address_count(targets)
    if count > ceiling:
        raise AgentExecutionLocationError(scan_agent_id, REASON_ADDRESS_LIMIT, f"{count}>{ceiling}")


def job_nmap_arguments(db: Session, job: ScanJob) -> str | None:
    """The port-bearing argument string this job was created with, or `None`.

    `_scan_setup` derives the same two values in the same order — the ad-hoc
    override encoded into the label wins over the profile's — and then falls
    back to the server's global `discovery_nmap_args`. This one deliberately
    stops short of that fallback: the global default describes the server
    scanner's own invocation and says nothing about what the operator asked an
    agent to open, so inheriting it would silently widen an agent request or
    refuse it against ports nobody named.
    """
    if job.label and job.label.startswith(_NMAP_OVERRIDE_PREFIX):
        return job.label[len(_NMAP_OVERRIDE_PREFIX) :]
    if job.profile_id:
        profile = db.get(DiscoveryProfile, job.profile_id)
        if profile is not None and profile.nmap_arguments:
            return cast(str, profile.nmap_arguments)
    return None


def _agent_tenant_id(db: Session, scan_agent_id: int | None) -> int | None:
    """The tenant an agent-executed job inherits (D-17).

    `None` for a server job, which is every job that predates Slice 4 and stays
    tenant-less exactly as it is today. Imported lazily for the reason
    `_granted_local_discovery_config` documents: `services/agent_discovery.py`
    imports this module.
    """
    if scan_agent_id is None:
        return None
    from app.services import agent_registry

    agent = agent_registry.get_agent(db, scan_agent_id)
    # `validate_agent_execution_location` has already refused a missing agent, so
    # this cannot be None in practice; it is written as a lookup rather than an
    # assertion because a job with the wrong tenant is worse than no job.
    return agent.tenant_id if agent is not None else None
