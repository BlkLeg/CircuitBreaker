"""May this agent run this discovery job? (Slice 4 §3)

Plan §3 requires the same answer at four checkpoints — profile save, ad hoc job
creation, dispatch, and the re-check the dispatcher owes a job that has been
sitting in the queue — so it is composed here once. Three of those callers owe a
user a 422 or a 409 naming what is wrong, and the fourth writes it to the job's
dispatch audit trail, which is why every denial carries a machine-readable
`reason` from the closed vocabulary below rather than prose.

This is `monitoring/probe_eligibility.py`'s twin, deliberately: the two answer
the same question about the same agent, and both derive scope from
`core.agent_scope` through that module's own `derive_agent_scope` so the two can
never disagree about what an agent may reach. Three things differ, each because
discovery differs:

* The question is about **prefixes**, not one address, so scope is judged by
  `agent_scope.network_in_scope` and never resolves a hostname — a discovery
  target is a CIDR by construction (`agent_capabilities` refuses
  `additional_hostnames` on `local_discovery` for the same reason).
* `degraded` collector readiness is a **refusal** here, where remote probing
  treats it as usable. A probe that half-works reports an execution error the
  result path already models; a sweep that half-works reports *fewer hosts*, and
  nothing in the discovery result contract distinguishes that from a segment
  that really is that empty. Silently short inventory is worse than no scan.
* Reachability is optional (`require_online`). D-5 parks a job for an offline
  agent as `queued` + `waiting_for_agent` instead of failing it, so being
  offline is a scheduling condition; a profile save that refused it would make
  an agent unusable from its first reboot onwards.

What this module deliberately does **not** do: it does not enforce
`max_addresses_per_job` or the `tcp_ports` set. Those are grant *limits* on a
particular request's size and shape rather than conditions on the agent, they
have their own error messages naming the offending number, and their callers
already hold the request. `agent_scope.address_count` is what they use.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import agent_scope
from app.core.time import utcnow
from app.db.models import AgentCapabilityReadiness
from app.services import agent_registry
from app.services.monitoring import probe_eligibility

CAPABILITY = "local_discovery"

# Machine-readable denial reasons. They are returned as the `reason` half of a
# 422/409 detail and recorded against the job, so they are constants shared with
# the API layer rather than strings rebuilt at each call site. The names that
# overlap `probe_eligibility` mean exactly the same thing there — a UI that has
# already learned `agent_inactive` must not have to learn a second spelling.
REASON_AGENT_MISSING = "agent_missing"
REASON_AGENT_INACTIVE = "agent_inactive"
REASON_CAPABILITY_DISABLED = "capability_disabled"
REASON_AGENT_OFFLINE = "agent_offline"
REASON_NO_LINK_OWNER = "no_link_owner"
REASON_READINESS_UNKNOWN = "readiness_unknown"
REASON_READINESS_DEGRADED = "readiness_degraded"
REASON_READINESS_UNAVAILABLE = "readiness_unavailable"
REASON_TENANT_MISMATCH = "tenant_mismatch"
REASON_OUT_OF_SCOPE = "out_of_scope"

# D-8: discovery collector state travels as ordinary `agent_capability_readiness`
# rows under these names. Listed in full because the agent detail page renders
# the set and a name invented at either end would render as a silent absence.
READINESS_COLLECTORS = ("discovery.neighbor", "discovery.icmp", "discovery.tcp", "discovery.dns")

# Only the connect sweep gates a job. `agent_connect` *is* the TCP connect sweep
# (`core/discovery_scan_types.AGENT_SCAN_TYPES`); the neighbor cache and the ICMP
# sweep only make it faster and reverse DNS only enriches it, and every one of
# them is legitimately unavailable in an unprivileged container that can still
# perform the scan completely. Denying on those would make such a host
# permanently ineligible for work it can do.
REQUIRED_READINESS_COLLECTORS = ("discovery.tcp",)

# `degraded` is refused rather than accepted — see the module docstring. It stays
# a distinct reason from `unavailable` so the UI can tell "it will try and see
# less" from "it cannot try at all"; both refuse.
_READINESS_DENIALS = {
    "degraded": REASON_READINESS_DEGRADED,
    "ready": None,
}

# Readiness rows have no TTL, so a row saying `ready` may predate an outage of
# any length and its age is the only evidence it still describes the running
# agent. Shares `probe_eligibility`'s default and its reasoning (three missed
# 15-minute reports) but takes its own environment variable, because an operator
# tuning one collector family's tolerance must not silently move the other's.
READINESS_MAX_AGE_S = int(
    os.getenv("CB_DISCOVERY_READINESS_MAX_AGE_S", str(probe_eligibility.READINESS_MAX_AGE_S))
)


@dataclass(frozen=True)
class Eligibility:
    """`ok` plus, on refusal, why.

    `detail` carries the specific — the agent status, the collector and its
    state, the scope decision and the prefix that produced it — for the operator
    and the audit row; `reason` stays the small closed vocabulary above so the
    API and the UI can switch on it.
    """

    ok: bool
    reason: str | None = None
    detail: str | None = None


def _denied(reason: str, detail: str | None = None) -> Eligibility:
    return Eligibility(ok=False, reason=reason, detail=detail)


async def evaluate_eligibility(
    db: Session,
    agent_id: int | None,
    *,
    targets: Sequence[str] = (),
    tenant_id: int | None = None,
    require_online: bool = True,
) -> Eligibility:
    """Answer §3's preconditions, in §3's order, for one agent and its targets.

    `targets` are the CIDRs the job would scan; an empty sequence asks only about
    the agent, which is what the revoke and capability-disable paths need when
    they have no particular job in hand. `tenant_id` is the job's or profile's
    tenant. `require_online` is what a creation-time caller drops (D-5).

    Caller owns the transaction; nothing here writes.
    """
    if agent_id is None:
        return _denied(REASON_AGENT_MISSING)

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:
        return _denied(REASON_AGENT_MISSING)
    if agent.status != "active":
        # `pending`, `rejected` and `revoked` share one reason and are told apart
        # by `detail`: the caller's remedy ("approve it", "re-enrol it") differs,
        # but the condition is the same and a per-status vocabulary would have to
        # be re-learned by every consumer whenever a status is added.
        return _denied(REASON_AGENT_INACTIVE, agent.status)

    grant = agent_registry.structured_grants_dict(db, agent_id).get(CAPABILITY)
    if grant is None or not grant.get("enabled"):
        return _denied(REASON_CAPABILITY_DISABLED)

    if require_online:
        if not await agent_registry.is_agent_online(agent_id):
            return _denied(REASON_AGENT_OFFLINE)
        # Presence and connection ownership expire together but are written by
        # different call sites; only the owner proves some worker can deliver a
        # `discovery.request` to this agent's socket at all.
        if await agent_registry.get_agent_connection_owner(agent_id) is None:
            return _denied(REASON_NO_LINK_OWNER)

    readiness = _readiness_denial(db, agent_id)
    if readiness is not None:
        return readiness

    # `probe_eligibility`'s tenant rule verbatim: refuse only when both sides
    # carry a tenant and they differ. A tenant-less job stays legal on a
    # tenant-scoped agent — the target is still bounded by that agent's own
    # directly connected networks — and a tenant-less agent is a global one.
    if agent.tenant_id is not None and tenant_id is not None and agent.tenant_id != tenant_id:
        return _denied(REASON_TENANT_MISMATCH, f"{tenant_id}!={agent.tenant_id}")

    scope = derive_discovery_scope(db, agent_id, grant.get("config"))
    for cidr in targets:
        decision = agent_scope.network_in_scope(scope, cidr)
        if not decision.allowed:
            # One reason, with the evaluator's own — `prefix_too_wide`,
            # `excluded_cidr`, `empty_scope` — in `detail`. The caller switches
            # on "the agent may not scan that"; the operator needs to know which
            # rule said so, and re-deriving it later from the CIDR is impossible.
            return _denied(REASON_OUT_OF_SCOPE, f"{decision.reason}:{decision.address or cidr}")

    return Eligibility(ok=True)


def derive_discovery_scope(
    db: Session, agent_id: int, config: Any = None
) -> agent_scope.EffectiveScope:
    """The agent's effective scope under its `local_discovery` grant.

    Delegates to `probe_eligibility.derive_agent_scope`, whose `CAPABILITY` is
    hardcoded to `remote_probe` — passing `config` explicitly is what keeps it
    out of that default, so the argument is not optional in practice and a
    `None` here means "look the grant up", not "no configuration". Re-querying
    `agent_networks` here instead would be a second DB→scope bridge to keep in
    step with the first.

    The `{}` fallback is load-bearing rather than defensive: an agent with no
    `local_discovery` grant row resolves no config at all, and `derive_agent_scope`
    reads a `None` config as "look my own grant up", which is the `remote_probe`
    one. Handing it an empty mapping is what makes an ungranted agent derive the
    registry defaults instead of silently inheriting whatever its probing grant
    widened — a substitution no denial anywhere would make visible.
    """
    if config is None:
        config = (agent_registry.structured_grants_dict(db, agent_id).get(CAPABILITY) or {}).get(
            "config"
        )
    return probe_eligibility.derive_agent_scope(
        db, agent_id, config if isinstance(config, dict) else {}
    )


def _readiness_denial(db: Session, agent_id: int) -> Eligibility | None:
    rows: dict[str, str] = {
        collector: state
        for collector, state in db.execute(
            select(AgentCapabilityReadiness.collector, AgentCapabilityReadiness.state).where(
                AgentCapabilityReadiness.agent_id == agent_id,
                AgentCapabilityReadiness.collector.in_(REQUIRED_READINESS_COLLECTORS),
                # Freshness is part of the query, not a post-filter: an old row is
                # evidence of nothing, and treating it as `ready` is how an agent
                # that lost its collector after a crash keeps receiving jobs. A
                # NULL `updated_at` fails this comparison and lands as unknown,
                # which is the same refusal for the same reason.
                AgentCapabilityReadiness.updated_at
                >= utcnow() - timedelta(seconds=READINESS_MAX_AGE_S),
            )
        ).all()
    }
    for collector in REQUIRED_READINESS_COLLECTORS:
        state = rows.get(collector)
        if state is None:
            return _denied(REASON_READINESS_UNKNOWN, collector)
        # Anything outside the known vocabulary is refused as unavailable rather
        # than admitted: a state written by a newer agent must not be read here
        # as permission.
        reason = _READINESS_DENIALS.get(state, REASON_READINESS_UNAVAILABLE)
        if reason is not None:
            return _denied(reason, f"{collector}:{state}")
    return None
