"""Which enrolled agents are still running under a unit that refuses AF_NETLINK?

RISK-011: the installer used to write `RestrictAddressFamilies=AF_UNIX AF_INET
AF_INET6`. The template is fixed, but a host installed before the fix keeps its
old unit, and on that host the kernel refuses every `socket(AF_NETLINK, ...)`
with EAFNOSUPPORT. That kills the neighbour-cache dump and — through
`net.Interfaces()` — the agent's own network facts, so its discovery and probe
scope is empty. Nothing else on the link breaks, which is exactly why these
hosts are easy to miss and why they are listed here instead of left for an
operator to find one Agent Detail page at a time.

An agent's `discovery.neighbor` readiness row is the evidence. Two shapes of it
are recognised, and nothing else:

* **Current agents** put `AF_NETLINK` in the row's `missing` list — a token, not
  prose, so the match does not depend on wording the agent is free to change
  (`discover.MissingAFNetlink` in apps/agent).
* **Agents built before that token existed** report the refused socket only as
  text. Their reason is fixed in every shipped binary: the collector's
  "open netlink socket" prefix followed by Go's EAFNOSUPPORT message. It is
  matched exactly, so a differently worded failure is never misfiled as this
  one — and those binaries cannot change, so the match cannot drift.

The query is read-only and bounded; it grants and changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Agent, AgentCapabilityReadiness

NEIGHBOR_COLLECTOR = "discovery.neighbor"
NETLINK_MISSING_TOKEN = "AF_NETLINK"
LEGACY_NETLINK_BLOCKED_REASON = (
    "discover: open netlink socket: address family not supported by protocol"
)
# Matches the other fleet drill-downs (`/server-key/pending`, `/tls-pin/pending`):
# a longer list than this is a rollout problem, not a page of rows to read.
NETLINK_BLOCKED_LIST_LIMIT = 200


@dataclass(frozen=True)
class NetlinkBlockedAgent:
    """One active agent whose sandbox refuses AF_NETLINK, with the row that says so.

    `legacy_report` is true when the agent predates the `missing` token: its
    row's remediation is the old generic wording, so a caller should present
    the unit fix itself rather than echo that row's instruction.
    """

    agent: Agent
    reason: str | None
    remediation: str | None
    reported_at: datetime | None
    legacy_report: bool


def list_netlink_blocked_agents(
    db: Session, limit: int = NETLINK_BLOCKED_LIST_LIMIT
) -> list[NetlinkBlockedAgent]:
    """Active agents whose latest `discovery.neighbor` row reports AF_NETLINK refused.

    Only `unavailable` rows count: the daemon overwrites the row with `disabled`
    when the discovery grant is revoked and with `ready` once the unit is
    rewritten, so a host drops off this list by itself the next time it
    reports — which is the evidence the remediation worked. Ordered most
    recently seen first, because an agent that is online can be fixed now.
    """
    missing_token = AgentCapabilityReadiness.missing.contains([NETLINK_MISSING_TOKEN])
    rows = db.execute(
        select(Agent, AgentCapabilityReadiness)
        .join(AgentCapabilityReadiness, AgentCapabilityReadiness.agent_id == Agent.id)
        .where(
            Agent.status == "active",
            AgentCapabilityReadiness.collector == NEIGHBOR_COLLECTOR,
            AgentCapabilityReadiness.state == "unavailable",
            or_(
                missing_token,
                AgentCapabilityReadiness.reason == LEGACY_NETLINK_BLOCKED_REASON,
            ),
        )
        .order_by(Agent.last_seen_at.desc().nulls_last(), Agent.id)
        .limit(limit)
    ).all()
    return [
        NetlinkBlockedAgent(
            agent=agent,
            reason=row.reason,
            remediation=row.remediation,
            reported_at=row.updated_at,
            legacy_report=NETLINK_MISSING_TOKEN not in (row.missing or []),
        )
        for agent, row in rows
    ]
