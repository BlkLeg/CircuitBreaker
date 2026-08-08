"""May this agent run this monitor's check right now? (Slice 3 §2)

§2 lists six preconditions for handing a check to a remote vantage — active
agent, `remote_probe` granted, a live connection, compatible probe readiness, a
target inside the grant's network scope, and no run already in flight. They are
composed here, once, because three callers need the identical answer and must
not drift: the remote dispatcher (`workers/monitor_probe_dispatch.py`), the
"check now" precheck that owes the user a 409 with the reason (D-14), and the
assignment write that refuses to save a monitor the agent could never reach.

Every denial names a machine-readable reason. It is written to
`monitor_items.probe_execution_reason` and `monitor_probe_runs.error_code`,
rendered on the monitor card, and returned as the 409 detail, so prose would
have to be re-parsed by all three.

What this module deliberately does **not** do:

* It never decides a target is *down*. An ineligible vantage is an execution
  condition; the target's last UP/DOWN state stands and no `avail` sample is
  written (§2, D-12).
* It never resolves anything itself unless it has to. IP literals are judged
  directly and only a hostname target costs a lookup; `resolver` is injectable
  so tests do not depend on the host's DNS. The agent resolves the same name
  again immediately before connecting and applies the same rule, which is what
  makes a rebinding resolver useless (§3).
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import agent_scope
from app.core.time import utcnow
from app.db.models import (
    AgentCapabilityReadiness,
    AgentNetwork,
    ComputeUnit,
    ExternalNode,
    Hardware,
    MonitorItem,
    MonitorProbeRun,
    Service,
)
from app.services import agent_registry

CAPABILITY = "remote_probe"

# Machine-readable denial reasons. `monitor_items.probe_execution_reason` is
# String(128) and these are the vocabulary its column comment names.
REASON_AGENT_MISSING = "agent_missing"
REASON_AGENT_INACTIVE = "agent_inactive"
REASON_CAPABILITY_DISABLED = "capability_disabled"
REASON_AGENT_OFFLINE = "agent_offline"
REASON_NO_LINK_OWNER = "no_link_owner"
REASON_READINESS_UNKNOWN = "readiness_unknown"
REASON_READINESS_UNAVAILABLE = "readiness_unavailable"
REASON_TENANT_MISMATCH = "tenant_mismatch"
REASON_UNRESOLVED_HOST = "unresolved_host"
REASON_OUT_OF_SCOPE = "out_of_scope"
REASON_PREVIOUS_RUN_IN_FLIGHT = "previous_run_in_flight"

# The statuses that hold the partial unique index on `monitor_probe_runs`.
_ACTIVE_RUN_STATUSES = ("queued", "dispatched")

# One readiness collector per check type (§5). `agent_capability_readiness`
# already accepts free-form collector names, so these need no schema change.
READINESS_COLLECTORS = {
    "icmp": "probe.icmp",
    "tcp": "probe.tcp",
    "http": "probe.http",
    "dns": "probe.dns",
}

# `degraded` still means the collector will attempt the check — DNS reports it
# when no resolver is configured, and the resulting failure is an execution
# error the result path already models. `unavailable`/`disabled` mean it will
# not attempt anything, which is a refusal to dispatch, not a check to run.
_USABLE_READINESS_STATES = frozenset({"ready", "degraded"})

# Readiness rows carry no TTL and `hello.readiness` is parsed but never
# persisted, so a row saying `ready` may predate an outage of any length and its
# age is the only evidence it still describes the running agent. The agent's
# floor between two `capability.readiness` frames is 15 minutes
# (`cmd/cb-agent/main.go`'s `readinessReportInterval`) and `OnConnected` forces
# one immediately, so three missed reports is the threshold: far enough out that
# a healthy agent never trips it, close enough that a row that survived a
# multi-hour outage is read as unknown rather than as ready.
READINESS_MAX_AGE_S = int(os.getenv("CB_PROBE_READINESS_MAX_AGE_S", "2700"))

Resolver = Callable[[str], Awaitable[Sequence[str]]]


@dataclass(frozen=True)
class Eligibility:
    """`ok` plus, on refusal, why.

    `detail` carries the specific — the agent status, the scope decision and the
    address that produced it — for the audit row and the operator; `reason`
    stays the small closed vocabulary above so UI and callers can switch on it.
    """

    ok: bool
    reason: str | None = None
    detail: str | None = None


def _denied(reason: str, detail: str | None = None) -> Eligibility:
    return Eligibility(ok=False, reason=reason, detail=detail)


async def default_resolver(host: str) -> list[str]:
    """Resolve *host* to every usable address, or none at all.

    Failure is silent by design: an unresolvable name is refused by the caller
    as `unresolved_host`, which is an execution condition, and must never reach
    the agent as a check that then reads as the target being down.
    """
    loop = asyncio.get_running_loop()
    try:
        # `socket.gaierror` is an OSError subclass, so this covers NXDOMAIN,
        # SERVFAIL and a dead resolver alike.
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    # dict, not set: every answer has to be evaluated and the refusal names the
    # first one that fails, so a stable order makes that message reproducible.
    return list(dict.fromkeys(str(info[4][0]) for info in infos if info[4]))


async def evaluate_eligibility(
    db: Session,
    monitor: MonitorItem,
    *,
    agent_id: int | None = None,
    ignore_run_id: str | None = None,
    resolver: Resolver | None = None,
) -> Eligibility:
    """Answer §2's six preconditions, in §2's order, for one monitor.

    `agent_id` overrides `monitor.probe_agent_id` so an assignment write can ask
    about an agent the monitor does not have yet. `ignore_run_id` is the run the
    caller already owns — the dispatcher's own run must not count as the run
    that blocks it. Caller owns the transaction; nothing here writes.
    """
    agent_id = agent_id if agent_id is not None else monitor.probe_agent_id
    if agent_id is None:
        return _denied(REASON_AGENT_MISSING)

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        return _denied(REASON_AGENT_MISSING)
    if agent.status != "active":
        return _denied(REASON_AGENT_INACTIVE, agent.status)

    grant = agent_registry.structured_grants_dict(db, agent_id).get(CAPABILITY)
    if grant is None or not grant.get("enabled"):
        return _denied(REASON_CAPABILITY_DISABLED)

    if not await agent_registry.is_agent_online(agent_id):
        return _denied(REASON_AGENT_OFFLINE)
    # Presence and connection ownership expire together but are written by
    # different call sites; only the owner proves some worker can deliver a
    # control frame to this agent's socket at all.
    if await agent_registry.get_agent_connection_owner(agent_id) is None:
        return _denied(REASON_NO_LINK_OWNER)

    readiness = _readiness_denial(db, agent_id, monitor.check_type)
    if readiness is not None:
        return readiness

    # D-9: refuse only when both sides carry a tenant and they differ. A
    # tenant-less standalone monitor stays legal on a tenant-scoped agent — the
    # target is still bounded by that tenant's own directly connected networks.
    monitor_tenant = _monitor_tenant_id(db, monitor)
    if agent.tenant_id is not None and monitor_tenant is not None:
        if agent.tenant_id != monitor_tenant:
            return _denied(REASON_TENANT_MISMATCH, f"{monitor_tenant}!={agent.tenant_id}")

    scope = derive_agent_scope(db, agent_id, grant.get("config"))
    resolved: Sequence[str] | None = None
    if not _is_ip_literal(monitor.host):
        resolved = list(await (resolver or default_resolver)(monitor.host))
        if not resolved:
            return _denied(REASON_UNRESOLVED_HOST, monitor.host)
    decision = agent_scope.evaluate(scope, monitor.host, resolved)
    if not decision.allowed:
        return _denied(REASON_OUT_OF_SCOPE, f"{decision.reason}:{decision.address or monitor.host}")

    if _active_run_exists(db, monitor.id, ignore_run_id=ignore_run_id):
        return _denied(REASON_PREVIOUS_RUN_IN_FLIGHT)

    return Eligibility(ok=True)


def derive_agent_scope(
    db: Session, agent_id: int, config: object | None = None
) -> agent_scope.EffectiveScope:
    """The agent's effective scope from its own reported networks plus its grant.

    `config` must come from `structured_grants_dict` / `default_config_for`, never
    from a bare `grant.config`: already-approved agents keep `config = {}` in the
    database and read the registry defaults at render time, and a migration must
    never backfill them.
    """
    if config is None:
        grant = agent_registry.structured_grants_dict(db, agent_id).get(CAPABILITY) or {}
        config = grant.get("config")
    facts = db.execute(
        select(AgentNetwork.facts).where(AgentNetwork.agent_id == agent_id)
    ).scalar_one_or_none()
    return agent_scope.derive_scope(facts, config if isinstance(config, dict) else None)


def _readiness_denial(db: Session, agent_id: int, check_type: str) -> Eligibility | None:
    collector = READINESS_COLLECTORS.get(check_type)
    if collector is None:
        # An unknown check type has no probe collector to be ready; the result
        # path already reports it, and refusing here would hide that behind a
        # readiness reason that is not the real problem.
        return None
    row = db.execute(
        select(AgentCapabilityReadiness.state, AgentCapabilityReadiness.updated_at).where(
            AgentCapabilityReadiness.agent_id == agent_id,
            AgentCapabilityReadiness.collector == collector,
        )
    ).first()
    if row is None:
        return _denied(REASON_READINESS_UNKNOWN, collector)
    state, updated_at = row
    if updated_at is None or updated_at < utcnow() - timedelta(seconds=READINESS_MAX_AGE_S):
        return _denied(REASON_READINESS_UNKNOWN, collector)
    if state not in _USABLE_READINESS_STATES:
        return _denied(REASON_READINESS_UNAVAILABLE, f"{collector}:{state}")
    return None


# `monitor_items` carries no tenant_id and is not in 0040_rls_policies, so
# nothing at the DB layer enforces D-9 — the monitor's tenant is whatever its
# target entity's is, and this is the only place that derives it. `compute_units`
# is the one target type with no column of its own (0040 lists the table but
# skips it for exactly that reason), so it takes its host's; a compute unit is
# never in a different tenant from the hardware it runs on.
_TENANT_SELECTS = {
    "hardware": lambda target_id: select(Hardware.tenant_id).where(Hardware.id == target_id),
    "compute_unit": lambda target_id: (
        select(Hardware.tenant_id)
        .select_from(ComputeUnit)
        .join(Hardware, Hardware.id == ComputeUnit.hardware_id)
        .where(ComputeUnit.id == target_id)
    ),
    "service": lambda target_id: select(Service.tenant_id).where(Service.id == target_id),
    "external_node": lambda target_id: select(ExternalNode.tenant_id).where(
        ExternalNode.id == target_id
    ),
}


def _monitor_tenant_id(db: Session, monitor: MonitorItem) -> int | None:
    build = _TENANT_SELECTS.get(monitor.target_type or "")
    if build is None or monitor.target_id is None:
        return None
    return db.execute(build(monitor.target_id)).scalar_one_or_none()


def _active_run_exists(db: Session, monitor_id: int, *, ignore_run_id: str | None) -> bool:
    stmt = select(MonitorProbeRun.id).where(
        MonitorProbeRun.monitor_id == monitor_id,
        MonitorProbeRun.status.in_(_ACTIVE_RUN_STATUSES),
    )
    if ignore_run_id is not None:
        stmt = stmt.where(MonitorProbeRun.run_id != ignore_run_id)
    return db.execute(stmt.limit(1)).first() is not None


def _is_ip_literal(host: str) -> bool:
    """Whether *host* needs resolving at all. `agent_scope.evaluate` judges a
    literal on its own and only consults `resolved` for a name."""
    try:
        ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return True
