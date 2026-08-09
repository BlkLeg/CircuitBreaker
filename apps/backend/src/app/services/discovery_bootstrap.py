"""Zero-configuration discovery bootstrap (Slice 4 plan §2/§3, Task 24, D-7).

This is the feature that makes the slice zero-configuration. An operator runs
one install command, approves the agent with normal defaults, and discovery of
that agent's own segments starts: plan §3's five steps — normalize the reported
subnets, compute effective safe scope, upsert one system-managed profile per
`(agent, subnet)`, queue an initial scan after a short jitter, and keep scanning
on a per-agent-jittered six-hourly cadence — with no CIDR entry, no profile, no
port list and nothing configured on the agent host at all.

**Every write goes through `discovery_profiles_service`** (Task 7). That module
owns the closed field list, derives `normalized_cidr`, is where D-14's
profile-disable cancellation lives, and is what reloads the cron scheduler. A
second writer constructing `DiscoveryProfile` rows here would be a second answer
to all four, and the one that matters most is the cancellation: a system profile
disabled without it leaves its dispatches open until the reconciler expires them
under the wrong reason.

**Nothing here decides what is safe.** The candidate set is
`EffectiveScope.direct_networks` from `core.agent_scope`, the same evaluator the
dispatcher, the ingest path and the Go agent all consult, so loopback,
link-local, point-to-point tunnels, the default route, public space and
over-wide prefixes are excluded by the shared rules rather than by a second copy
of them here (D-15). The one judgement this module adds is the grant's
`max_addresses_per_job` ceiling, which `discovery_eligibility` deliberately
leaves to whoever holds the request — and here the request is being *invented*,
so there is no user to refuse: a subnet too large to sweep is simply not
automatic scope, and an administrator who wants it can still create a profile
for it by hand.

**Ordering (D-14).** The trigger is `agent_registry.record_network_facts`, which
runs inside the reporting frame's transaction. Nothing here may run there: this
module creates profiles and jobs through services that commit, and an initial
scan dispatched for a report a rollback then discards is a scan of a scope the
server does not believe in. So `schedule_bootstrap` only *defers* — it hands
`_bootstrap_in_session` to the event loop, and neither report path
(`api/ws_agents.py`'s hello block and `agent_telemetry.ingest_readiness`) awaits
anything between `record_network_facts` and its own `db.commit()`, so the
deferred task cannot start until that commit has returned. The pass then runs
against committed state in its own session, which is also what makes a rolled-
back report harmless: it re-derives everything from `agent_networks` and finds
nothing to do.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import agent_scope
from app.core.discovery_scan_types import AGENT_SCAN_TYPES
from app.db.models import Agent, DiscoveryProfile
from app.schemas.discovery import DiscoveryProfileCreate, DiscoveryProfileUpdate
from app.services import (
    agent_registry,
    discovery_eligibility,
    discovery_profiles_service,
    discovery_service,
)

logger = logging.getLogger(__name__)

# The `managed_by` marker for a profile this module owns and may re-upsert. NULL
# is a user-created profile, which is never read, written or disabled from here.
# It is also the predicate of D-7's partial unique index
# `uq_discovery_profiles_system_agent_cidr`, so the string has to match exactly.
MANAGED_BY_SYSTEM = "system"

# What the audit trail records as the author of an automatic profile. Not
# "system" (`write_log`'s default for anything unattributed): an operator
# looking at a profile they did not create needs to see *which* automatic
# process created it, and this is the only one that writes discovery profiles.
BOOTSTRAP_ACTOR = "discovery-bootstrap"

# `ScanJob.triggered_by`, alongside the existing "api", "scheduler", "prober"
# and "proxmox". Distinct from "scheduler" on purpose: the six-hourly cron runs
# are that one, and this is the single post-approval scan plan §3 step 4 asks
# for, which is the one an operator is watching for after enrolment.
BOOTSTRAP_TRIGGERED_BY = "bootstrap"

# Plan §3: an agent profile exposes the focused connect scan and nothing else.
# Read from the vocabulary rather than spelled out so this cannot drift from
# what `validate_scan_types` will accept for an agent execution location.
SYSTEM_PROFILE_SCAN_TYPES = sorted(AGENT_SCAN_TYPES)

# Plan §3 step 5: "schedule recurring scans every six hours with per-agent
# jitter". `schedule_cron` is the only cadence field `discovery_profiles` has
# and APScheduler's `misfire_grace_time` is not jitter, so the spread has to be
# encoded in the expression itself — hence the derived minute (D-7). Derived
# once, for a brand-new profile only: re-deriving on every pass would revert
# plan §6's "edit cadence and scan depth" the moment a readiness frame arrived,
# which is at most fifteen minutes later.
RECURRING_SCAN_INTERVAL_HOURS = 6
_CRON_MINUTE_MODULUS = 60

# Plan §3 step 4's "short jitter". A floor, because approval and the first
# report are the same operator action and a scan starting in the same instant
# would race the readiness the dispatcher re-checks; a spread, because a fleet
# that reconnects together after a backend restart would otherwise dispatch
# together and queue behind one concurrency ceiling. Both bounded and both
# small: the operator is watching, and plan §3 wants approval to "produce useful
# data promptly".
INITIAL_SCAN_JITTER_FLOOR_S = 5.0
INITIAL_SCAN_JITTER_SPREAD_S = 60.0


def system_profile_cron(agent_id: int) -> str:
    """The recurring cadence a brand-new system profile is created with (D-7)."""
    minute = agent_id % _CRON_MINUTE_MODULUS
    return f"{minute} */{RECURRING_SCAN_INTERVAL_HOURS} * * *"


def initial_scan_delay_s(agent_id: int) -> float:
    """How long after its first report an agent's initial scan starts.

    Derived from the agent id rather than drawn at random, for the reason D-7
    derives the cron minute the same way: the spread has to be *stable* per
    agent so a reconnect storm cannot land two agents on the same instant twice
    in a row, and a deterministic delay is one an operator can predict and a
    test can pin.
    """
    return INITIAL_SCAN_JITTER_FLOOR_S + float(agent_id % int(INITIAL_SCAN_JITTER_SPREAD_S))


@dataclass(frozen=True)
class BootstrapOutcome:
    """What one pass did, for the caller's log and for the tests.

    `skipped_reason` is `discovery_eligibility`'s closed vocabulary — the same
    string the profile-save 422 and the dispatch audit row carry — so an
    operator reading "why is nothing being discovered" gets one answer from
    every checkpoint rather than three spellings of it.
    """

    agent_id: int
    created_profile_ids: tuple[int, ...] = ()
    reenabled_profile_ids: tuple[int, ...] = ()
    disabled_profile_ids: tuple[int, ...] = ()
    queued_job_ids: tuple[int, ...] = ()
    skipped_reason: str | None = None

    def __bool__(self) -> bool:
        return bool(
            self.created_profile_ids
            or self.reenabled_profile_ids
            or self.disabled_profile_ids
            or self.queued_job_ids
        )


def eligible_subnets(scope: agent_scope.EffectiveScope, *, address_ceiling: int) -> list[str]:
    """The directly connected subnets that may become automatic scope (plan §7).

    `direct_networks` and not `networks`: the latter also carries an
    administrator's `additional_cidrs`, which are *routed* overrides they added
    deliberately, and minting an automatic profile for one would be this module
    deciding something the operator did not ask for. Plan §3 step 6 is about a
    subnet appearing on and disappearing from the agent's own interfaces, and
    only `direct_networks` answers that question.

    `network_in_scope` still runs over each one even though every entry came out
    of the derivation: it is what applies the `MIN_SCOPE_PREFIX_*` width ceiling
    and the administrator's `excluded_cidrs`, neither of which `derive_scope`
    consults — an excluded subnet is still a directly connected one.
    """
    chosen: list[str] = []
    for cidr in scope.direct_networks:
        decision = agent_scope.network_in_scope(scope, cidr)
        if not decision.allowed:
            logger.debug(
                "discovery bootstrap: %s is not automatic scope (%s)", cidr, decision.reason
            )
            continue
        count = agent_scope.address_count([cidr])
        if count > address_ceiling:
            # Not an error and not a refusal an operator has to see: no bounded
            # job could cover it, so it is simply not automatic. A `/16` clears
            # `MIN_SCOPE_PREFIX_V4` and still holds sixteen times the default
            # ceiling, which is why this test is separate from the width one.
            logger.info(
                "discovery bootstrap: %s covers %d addresses, over the %d ceiling; "
                "not creating an automatic profile for it",
                cidr,
                count,
                address_ceiling,
            )
            continue
        chosen.append(cidr)
    return chosen


async def run_bootstrap(db: Session, agent_id: int) -> BootstrapOutcome:
    """One idempotent pass: upsert this agent's system profiles and scan the new ones.

    Caller owns the session. Safe to run as often as an agent reports, which is
    the point — plan §3 requires that "repeated hello/readiness frames must not
    create duplicate profiles or scans", so the whole pass is expressed as a
    difference between what the agent currently reports and what is already
    stored, and an unchanged report produces no writes at all.

    Eligibility is asked first and refuses silently. A hello carries `networks`
    before any collector readiness row exists, so the very first pass after
    approval is normally refused with `readiness_unknown`; the readiness frame
    that follows is what makes the agent eligible, and it is why the trigger
    fires on a report's *presence* rather than on a change (see
    `agent_registry.record_network_facts`). Refusing silently is also what keeps
    every non-discovery agent's report cheap: an agent with no `local_discovery`
    grant leaves here after two queries.

    `require_online=False`, matching every other creation-time checkpoint (D-5):
    an offline agent's job parks as `queued`/`waiting_for_agent` rather than
    failing, so reachability is a scheduling condition and not a reason to skip
    creating the profile.
    """
    eligibility = await discovery_eligibility.evaluate_eligibility(
        db, agent_id, require_online=False
    )
    if not eligibility.ok:
        logger.debug(
            "discovery bootstrap: agent %s not eligible (%s: %s)",
            agent_id,
            eligibility.reason,
            eligibility.detail,
        )
        return BootstrapOutcome(agent_id=agent_id, skipped_reason=eligibility.reason)

    agent = agent_registry.get_agent(db, agent_id)
    if agent is None:  # pragma: no cover - `evaluate_eligibility` already refused it
        return BootstrapOutcome(
            agent_id=agent_id, skipped_reason=discovery_eligibility.REASON_AGENT_MISSING
        )

    # Imported here rather than at module scope because `agent_discovery`
    # imports `discovery_service`, which this module also imports; read through
    # that module's own reader so the ceiling this pass applies is the one the
    # dispatcher and the validator apply.
    from app.services.agent_discovery import discovery_grant_config

    config = discovery_grant_config(db, agent_id)
    scope = discovery_eligibility.derive_discovery_scope(db, agent_id, config)
    wanted = eligible_subnets(
        scope, address_ceiling=discovery_service.granted_address_ceiling(config)
    )

    stored = _system_profiles(db, agent_id)
    by_cidr: dict[str, DiscoveryProfile] = {}
    for row in stored:
        # A system row with no resolvable subnet cannot be keyed on, and D-7's
        # partial index does not constrain NULLs, so there could be several.
        # They fall through to the disable pass below, which is the right answer
        # for a system profile that names no subnet this agent reports.
        if row.normalized_cidr is not None:
            by_cidr.setdefault(row.normalized_cidr, row)

    # Plan §3's closing paragraph, read on step 4: queueing a scan *is*
    # scheduling, so a held agent gets its profiles and none of the scans. The
    # profiles are still upserted because a pause must delete nothing — the row
    # is what carries the subnet's identity, its cron and its history, and
    # `enabled = 0` is reserved for a subnet that has actually gone away.
    paused = discovery_service.agent_scheduling_paused(db, agent_id)

    created: list[int] = []
    reenabled: list[int] = []
    queued: list[int] = []

    # Appearances first, disappearances second — plan §3 step 6's own order, so
    # an agent whose subnet moved never has a moment with neither profile on.
    for cidr in wanted:
        profile: DiscoveryProfile | None = by_cidr.get(cidr)
        try:
            if profile is None:
                profile = _create_system_profile(db, agent, cidr)
                created.append(profile.id)
            elif not profile.enabled:
                # The subnet came back. Re-enabled rather than re-created: the
                # job and result history hanging off the original row is the
                # whole reason a disappearance disables instead of deleting.
                _reenable(db, profile)
                reenabled.append(profile.id)
            else:
                continue
        except Exception:
            # One subnet the server cannot express as a profile — an address
            # outside the global scan ACL, a name collision, a racing worker
            # that won D-7's unique index — must not cost this agent its other
            # segments. The next report retries it.
            logger.warning(
                "discovery bootstrap: could not upsert the system profile for agent %s %s",
                agent_id,
                cidr,
                exc_info=True,
            )
            continue
        if paused:
            continue  # the profile stands; only the automatic scan is withheld
        try:
            queued.append(_queue_initial_scan(db, agent, profile, cidr))
        except Exception:
            # The profile stands and its cron will scan it within six hours;
            # only the prompt first look is lost.
            logger.warning(
                "discovery bootstrap: could not queue the initial scan for agent %s %s",
                agent_id,
                cidr,
                exc_info=True,
            )

    disabled: list[int] = []
    for profile in stored:
        if not profile.enabled or profile.normalized_cidr in wanted:
            continue
        try:
            # D-14's entry point, not a local `enabled = 0`: this is where the
            # in-flight dispatches for the vanished subnet are closed with
            # `profile_disabled` and the `discovery.cancel` frames published
            # after the commit. Once the profile is off, nothing else would
            # ever close them — `dispatch_frame`'s capability gate drops the
            # agent's own terminal summary.
            discovery_profiles_service.disable_profile(db, profile.id, BOOTSTRAP_ACTOR)
            disabled.append(profile.id)
        except Exception:
            logger.warning(
                "discovery bootstrap: could not disable the system profile %s for agent %s",
                profile.id,
                agent_id,
                exc_info=True,
            )

    return BootstrapOutcome(
        agent_id=agent_id,
        created_profile_ids=tuple(created),
        reenabled_profile_ids=tuple(reenabled),
        disabled_profile_ids=tuple(disabled),
        queued_job_ids=tuple(queued),
    )


def _system_profiles(db: Session, agent_id: int) -> list[DiscoveryProfile]:
    """This agent's automatic profiles, and only those.

    The `managed_by` predicate is the whole of plan §3's "user-created profiles
    remain separate and are never overwritten": a profile an operator wrote for
    the same agent and the same CIDR is invisible from here, so it can be
    neither re-tuned nor disabled by an automatic pass. D-7's partial unique
    index carries the same predicate, which is what lets both rows exist.
    """
    return list(
        db.execute(
            select(DiscoveryProfile)
            .where(
                DiscoveryProfile.scan_agent_id == agent_id,
                DiscoveryProfile.managed_by == MANAGED_BY_SYSTEM,
            )
            .order_by(DiscoveryProfile.id)
        )
        .scalars()
        .all()
    )


def _profile_name(agent: Agent, cidr: str) -> str:
    """A name an operator can recognize in the profile list.

    Written once, at creation, and never rewritten by a later pass — a renamed
    agent leaves a stale-looking profile name, which is the cheaper of the two
    mistakes: the alternative overwrites a name an administrator chose.
    """
    label = agent.name or agent.hostname or f"agent {agent.id}"
    return f"{label} — {cidr}"


def _create_system_profile(db: Session, agent: Agent, cidr: str) -> DiscoveryProfile:
    """Mint the automatic profile for one subnet (plan §3 step 3).

    `managed_by` is passed as the keyword-only server-set argument
    `create_profile` reserves for exactly this: no request schema carries it, so
    an API client cannot park a row on the slot this module owns.

    `cidr` is already `agent_scope`'s canonical form, so the `normalized_cidr`
    the profile service derives from it is the same string this pass keys on —
    which is what makes the upsert idempotent against D-7's unique index rather
    than merely usually idempotent.
    """
    payload = DiscoveryProfileCreate(
        name=_profile_name(agent, cidr),
        cidr=cidr,
        scan_types=list(SYSTEM_PROFILE_SCAN_TYPES),
        scan_agent_id=agent.id,
        # The grant's own `tcp_ports` are what the dispatcher sends when a job
        # names no `-p` spec, so the automatic profile deliberately names none:
        # the port set stays a central capability setting rather than being
        # copied into every profile, where an operator editing the grant would
        # then have to edit each one.
        nmap_arguments=None,
        schedule_cron=system_profile_cron(agent.id),
        enabled=True,
    )
    return discovery_profiles_service.create_profile(
        db, payload, BOOTSTRAP_ACTOR, managed_by=MANAGED_BY_SYSTEM
    )


def _reenable(db: Session, profile: DiscoveryProfile) -> None:
    """Turn a returning subnet's profile back on, and change nothing else.

    `model_validate` rather than the constructor, for the reason
    `discovery_profiles_service.disable_profile` documents: `update_profile`
    re-checks the execution location only for the fields the payload actually
    names, and a keyword-constructed model would name every optional one — which
    would also mean writing back a `schedule_cron` of None over an administrator's.
    """
    discovery_profiles_service.update_profile(
        db,
        profile.id,
        DiscoveryProfileUpdate.model_validate({"enabled": True}),
        BOOTSTRAP_ACTOR,
    )


def _queue_initial_scan(db: Session, agent: Agent, profile: DiscoveryProfile, cidr: str) -> int:
    """Plan §3 step 4: one bounded scan, shortly after the subnet appears.

    Through `create_scan_job` like every other execution path, so the job gets
    the same scan-type validation, the same global scan ACL, the same
    execution-location checkpoint and the same tenant derivation (D-17) that a
    manual scan does — an automatic job that skipped any of them would be the
    one job in the product nobody validated.

    Only ever called for a subnet that has just *appeared* (created or
    re-enabled). A pass over an unchanged report queues nothing, which is plan
    §3's "repeated hello/readiness frames must not create duplicate profiles or
    scans"; the recurring cron owns every scan after the first.
    """
    job = discovery_service.create_scan_job(
        db,
        target_cidr=cidr,
        scan_types=list(SYSTEM_PROFILE_SCAN_TYPES),
        profile_id=profile.id,
        triggered_by=BOOTSTRAP_TRIGGERED_BY,
        scan_agent_id=agent.id,
    )
    _start_after_delay(job.id, initial_scan_delay_s(agent.id))
    return job.id


def _start_after_delay(job_id: int, delay_s: float) -> None:
    """Start a queued job's dispatch after the jitter, without blocking anything.

    `call_later` rather than a sleeping task: the delay is the whole point and a
    coroutine that awaits it would have to be tracked and cancelled on shutdown
    for no gain. The job row is already `queued` and durable before this is
    called, so a delay that never fires — a worker restart inside the window —
    costs the scan its promptness and nothing else: both queued-backlog drains
    (`discovery_scheduler._schedule_queued_scan_jobs` and
    `agent_discovery_reconcile._drain_queued_jobs`) pick it up.

    `schedule_discovery_scan_job` is resolved at fire time rather than bound
    here so the module attribute stays the single dispatch entry point.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "discovery bootstrap: no running event loop to start scan job %s on; "
            "it stays queued for the next reconciliation pass",
            job_id,
        )
        return
    loop.call_later(delay_s, discovery_service.schedule_discovery_scan_job, job_id)


def schedule_bootstrap(agent_id: int) -> bool:
    """The trigger `agent_registry.record_network_facts` fires. Publishes nothing itself.

    Deferred rather than run inline because the caller is mid-transaction and
    this pass commits (D-14, and the module docstring): a profile created and a
    scan dispatched for a network report that a failed commit then discards is
    work against a scope the server does not believe in. Borrows
    `monitor_service._publish_soon`, which that function's own docstring calls
    the single home of the `get_running_loop()` + `create_task` idiom, so a
    deferred bootstrap behaves exactly like a deferred cancellation.

    Returns False, having scheduled nothing, when there is no loop — which is
    every synchronous `def` route on FastAPI's threadpool. Nothing is lost: this
    is a reconciliation of stored state, and the agent's next report (at most
    one `capability.readiness` interval away) runs the identical pass.
    """
    from app.services.monitor_service import _publish_soon

    return _publish_soon("discovery bootstrap", lambda: _bootstrap_in_session(agent_id))


async def _bootstrap_in_session(agent_id: int) -> None:
    """`run_bootstrap` for the deferred entry point, which owns no session.

    Its own session on purpose: the caller's is mid-transaction and may still
    roll back, and this pass must see only committed facts. Nothing escapes —
    this runs as a bare task on the event loop that serves the agent's `/link`
    socket, and an exception raised here would surface only as asyncio's generic
    "exception was never retrieved". A failed pass is retried by the agent's
    next report.
    """
    from app.db.session import get_session_context

    try:
        with get_session_context() as db:
            outcome = await run_bootstrap(db, agent_id)
    except Exception:
        logger.exception("discovery bootstrap failed for agent %s", agent_id)
        return
    if outcome:
        logger.info(
            "discovery bootstrap for agent %s: created=%s re-enabled=%s disabled=%s scans=%s",
            agent_id,
            outcome.created_profile_ids,
            outcome.reenabled_profile_ids,
            outcome.disabled_profile_ids,
            outcome.queued_job_ids,
        )


__all__ = [
    "BOOTSTRAP_ACTOR",
    "BOOTSTRAP_TRIGGERED_BY",
    "INITIAL_SCAN_JITTER_FLOOR_S",
    "INITIAL_SCAN_JITTER_SPREAD_S",
    "MANAGED_BY_SYSTEM",
    "RECURRING_SCAN_INTERVAL_HOURS",
    "SYSTEM_PROFILE_SCAN_TYPES",
    "BootstrapOutcome",
    "eligible_subnets",
    "initial_scan_delay_s",
    "run_bootstrap",
    "schedule_bootstrap",
    "system_profile_cron",
]
