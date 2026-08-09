"""One agent dispatch, end to end: `discovery.request` out, `discovery.finding` in (§3, §4).

Both halves live here because they are two ends of one lease. The dispatcher
mints `scan_jobs.dispatch_id`, snapshots the scope version onto the job and
publishes the request; ingest judges every finding against that same row and
the terminal summary closes it. Splitting them across modules is how the token
minted by one and the token accepted by the other come to mean different things.

**Dispatch** (`dispatch_discovery_job`) mirrors
`workers/monitor_probe_dispatch.py` and documents its three deliberate
divergences at the function itself: the claim is a compare-and-set because a
discovery lease lives on the job row rather than on a row of its own, an offline
agent parks the job instead of failing it (D-5), and the request is published
*after* the claim commits because an agent answers within milliseconds.

**Ingest** (`ingest_discovery_finding`) is the interesting half.
`probe.result` (`services/agent_probe.py`) is the model, and the acceptance
rules are enforced here in the same fixed order for the same reason: this is the
only inbound frame that puts agent-authored rows in front of an operator for
review, and a bad one becomes a `Hardware` record the moment somebody clicks
accept. Every rule below is pinned by a named test in
`tests/services/test_agent_discovery_ingest.py`:

1. **Size, before anything parses.** Nothing upstream bounds an inbound frame —
   `api/ws_agents.py`'s link read is a bare `receive_bytes()` and
   `agent_link.receive_frame` only parses JSON — so this handler is the cap. A
   `discovery.finding` is a spooled data frame, so the shape this has to survive
   is a whole outage's worth of oversized bodies replayed at reconnect.
2. **Authentication, as a triple.** The `dispatch_id`, the job it names and the
   authenticated agent must all agree, and so must the job's tenant. `dispatch_id`
   is a server-minted opaque 128-bit token and is the only identifier that ever
   reaches the agent, so a guessed `scan_job_id` buys nothing. A mismatch is a
   `capability_violation` — it is what a stolen token looks like, not a schema
   mistake.
3. **The lease, against server receipt time.** A spooled frame keeps its original
   producer `TS` (the Go agent stamps `TS` only when it is zero), so `frame.ts` is
   agent-clock provenance and never arrival time. Past
   `dispatch_deadline_at + LATE_FINDING_GRACE` the finding is refused, because the
   reconciler (Task 23) has already given the dispatch up and derives its own
   grace from this module's constant.
4. **Targets, then the scope snapshotted on the job (D-16).** The agent's *live*
   scope is deliberately not the authority: a sender that can move its own scope
   between dispatch and ingest — by reporting a new interface — could otherwise
   widen what it is allowed to report about. `job.scope_version` is the version
   that was in force when the request was built, so a finding arriving under any
   other version is refused outright rather than judged against a scope nobody
   authorized.
5. **Idempotency, by index and not by pre-check.** Two spool replays racing on
   separate connections both pass a `SELECT`; only `uq_scan_results_job_finding`
   stops the second `INSERT`. The insert therefore runs inside a SAVEPOINT and an
   `IntegrityError` is the duplicate answer.
6. **A ceiling on how many findings one dispatch may produce.** The lower of the
   agent's own `max_addresses_per_job` grant and what the job's *own* targets
   could honestly produce, plus a small summary allowance, enforced as a
   compare-and-set on `scan_jobs.finding_count` so two concurrent ingests cannot
   both squeeze past it. Without it a 2048-address /21 target admits unbounded
   distinct agent-chosen `finding_id`s, each fanning out through
   `discovery_service._emit_ws_event` to every connected client — and without the
   job's half, so does a /29.

**Log hygiene (plan §7).** `hostname`, `banner` and `evidence` are untrusted
observations — a PTR answer from a resolver the agent does not control, whatever
bytes a service chose to send, and free text respectively. None of them appears
in a rejection reason, a log line or an `agent_events.detail`; a reason carries a
machine-readable code and at most the address, and even that goes through
`core.log_sanitize.safe_log_fragment` so it cannot forge a second log record.
The untrusted values still reach `scan_results` verbatim, because a review queue
that sanitizes its own evidence is not evidence.

**The terminal summary** takes every check above and then closes the job
through `discovery_service.finalize_agent_job` — terminal status, timestamps,
the ordinary `scan_completed`/`scan_failed` audit row and the ordinary
`job_update`/`job_progress` events — while writing no `ScanResult` of its own
and touching none of the counters the host findings accumulated (D-10).
`SUMMARY_FINDING_ALLOWANCE` is the headroom the per-dispatch ceiling reserves
for it. Closing the job is also what makes a finding arriving *after* it
refusable, which is why cancellation being best-effort costs nothing.

Speed matters. This runs on the `/link` socket read loop, and that loop is what
advances `last_heartbeat_at` against the server's 60 s dead-link deadline — so
the accepted path is a handful of indexed lookups, one insert and one commit.
The grant and the scope it derives are therefore resolved *once* per frame in
`ingest_discovery_finding` and passed down; deriving them again inside
`_authorized_address` and `_record_host_finding` made three round trips per
finding, on the frame type a whole sweep produces thousands of.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, cast

from pydantic import ValidationError
from sqlalchemy import ColumnElement, CursorResult, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import agent_scope
from app.core.log_sanitize import safe_log_fragment
from app.core.time import utcnow, utcnow_iso
from app.db.models import Agent, ScanJob, ScanResult
from app.schemas.agent_frame import (
    DISCOVERY_KIND_SUMMARY,
    DISCOVERY_KINDS,
    MAX_DISCOVERY_TARGETS,
    TYPE_DISCOVERY_CANCEL,
    TYPE_DISCOVERY_REQUEST,
    DiscoveryCancelPayload,
    DiscoveryFindingPayload,
    DiscoveryRequestPayload,
)
from app.schemas.discovery import ScanResultOut
from app.services import (
    agent_registry,
    agent_telemetry,
    discovery_eligibility,
    discovery_result_service,
    discovery_service,
)
from app.services.agent_capabilities import (
    _LOCAL_DISCOVERY_BOUNDS,
    _LOCAL_DISCOVERY_DEFAULT_CONFIG,
)

# The DB -> scope bridge, borrowed rather than restated. `discovery_eligibility`
# owns it because every §3 checkpoint already calls that module, and a second
# wrapper here is how the dispatcher and the ingest path come to disagree about
# what an agent may report on — including over what an agent with no
# `local_discovery` grant row derives.
from app.services.discovery_eligibility import derive_discovery_scope
from app.services.discovery_network import PORT_SERVICE_MAP

_logger = logging.getLogger(__name__)

CAPABILITY = "local_discovery"

# Plan §4's limit for one finding, enforced on the raw mapping before validation.
# The schema's own field bounds add up to well under this; the gap is deliberate
# headroom so a legitimate frame is never refused on a byte count, while a
# hostile 40 MiB body is refused without ever being parsed.
MAX_FINDING_BYTES = 16 << 10

# A finding is judged against the server's own clock, so a spooled batch cannot
# walk past a lease the reconciler already expired. `agent_discovery_reconcile`
# (Task 23) derives its own grace from this constant rather than restating it,
# exactly as `monitoring/probe_reconcile` does against `agent_probe`.
LATE_FINDING_GRACE = timedelta(seconds=30)

# Ceiling headroom for the terminal summary (and a retry or two of it), on top of
# the address budget the grant allows. Small on purpose: it is an allowance for a
# frame that arrives once per dispatch, not a second budget.
SUMMARY_FINDING_ALLOWANCE = 4
# The server-side hard ceiling on `max_addresses_per_job`, read from the one
# place that defines it so the two cannot drift.
_MAX_ADDRESSES_PER_JOB = _LOCAL_DISCOVERY_BOUNDS["max_addresses_per_job"][1]
# What a dispatch may produce when the grant says nothing usable. Fail-closed to
# the hard ceiling, never to "no limit".
MAX_FINDINGS_PER_DISPATCH = _MAX_ADDRESSES_PER_JOB + SUMMARY_FINDING_ALLOWANCE

# D-4. The `scan_jobs.error_reason` vocabulary the agent execution path writes.
# Machine-readable constants rather than prose, because the frontend's history
# filter and the audit trail both read them and neither may be shown a sentence.
ERROR_AGENT_UNAVAILABLE = "agent_unavailable"
ERROR_AGENT_DISCONNECTED = "agent_disconnected"
ERROR_AGENT_EXECUTION_ERROR = "agent_execution_error"
ERROR_AGENT_REJECTED = "agent_rejected"
ERROR_DISPATCH_FAILED = "dispatch_failed"
ERROR_SCOPE_CHANGED = "scope_changed"
ERROR_CAPABILITY_DISABLED = "capability_disabled"
ERROR_PROFILE_DISABLED = "profile_disabled"
JOB_ERROR_REASONS = frozenset(
    {
        ERROR_AGENT_UNAVAILABLE,
        ERROR_AGENT_DISCONNECTED,
        ERROR_AGENT_EXECUTION_ERROR,
        ERROR_AGENT_REJECTED,
        ERROR_DISPATCH_FAILED,
        ERROR_SCOPE_CHANGED,
        ERROR_CAPABILITY_DISABLED,
        ERROR_PROFILE_DISABLED,
    }
)

# Rejection reasons that are not job outcomes. They travel into `agent_events`
# and nowhere else, so they are named separately from the D-4 vocabulary above.
REASON_AGENT_INACTIVE = "agent_inactive"
REASON_UNKNOWN_DISPATCH = "unknown_dispatch"
REASON_DISPATCH_OWNER_MISMATCH = "dispatch_owner_mismatch"
REASON_DISPATCH_JOB_MISMATCH = "dispatch_job_mismatch"
REASON_TENANT_MISMATCH = "tenant_mismatch"
REASON_DISPATCH_CLOSED = "dispatch_closed"
REASON_LATE_FINDING = "late_finding"
REASON_MISSING_ADDRESS = "missing_address"
REASON_OUT_OF_TARGET = "out_of_target"
REASON_FINDING_CEILING = "finding_ceiling_exceeded"
# A job asking for more prefixes than one `discovery.request` can carry.
# `address_limit_exceeded`'s sibling and deliberately spelled the same way, so an
# operator reading `error_text` does not have to learn that one limit counts
# addresses and the other counts prefixes from two unrelated phrasings.
REASON_TARGET_LIMIT = "target_limit_exceeded"

# What `ingest_discovery_finding` did, for the caller and for the tests. Not an
# audit vocabulary — `scan_results` and `agent_events` are that.
DISPOSITION_ACCEPTED = "accepted"
DISPOSITION_DUPLICATE = "duplicate"
DISPOSITION_SUMMARY = "summary"
# A finding for a dispatch the *server itself* cancelled. Not a rejection: the
# frame that most reliably lands here is the agent's correct answer to the
# server's own `discovery.cancel` — its terminal summary with
# `outcome="cancelled"` — plus whatever host findings were already in the spool
# when the cancel arrived. Recording those as protocol violations would audit a
# well-behaved agent for every ordinary administrator cancellation.
DISPOSITION_CANCELLED = "cancelled_dispatch"

# The audit trail a rejection lands in. `capability_violation` is reserved for
# the cases where the agent reached for something that is not its to touch —
# the same distinction `agent_link.dispatch_frame` draws for an ungranted frame
# type, and `agent_probe` for a forged run token.
EVENT_PROTOCOL_VIOLATION = "protocol_violation"
EVENT_CAPABILITY_VIOLATION = "capability_violation"

# The `scan_jobs.dispatch_status` values that still accept a finding. Anything
# else means the server closed the dispatch — by cancelling it, by accepting its
# terminal summary, or by expiring it — and cancellation is best-effort, so a
# finding arriving afterwards must be refused here regardless of whether the
# `discovery.cancel` was ever delivered.
_OPEN_DISPATCH_STATUSES = frozenset({"dispatched", "running"})
# The job statuses that go with them. Checked separately because a job can be
# cancelled through `DELETE /discovery/jobs/{id}` without the dispatch lease
# having been touched yet.
_OPEN_JOB_STATUSES = frozenset({"queued", "running"})

# `discovery_result_service`'s verdict -> the `scan_jobs` counter it increments.
# D-10: the agent path increments, because it has no finished batch to write
# absolutely from the way `_scan_import` does.
_COUNTER_FOR_CLASSIFICATION = {
    discovery_result_service.CLASSIFICATION_NEW: "hosts_new",
    discovery_result_service.CLASSIFICATION_MATCHED: "hosts_updated",
    discovery_result_service.CLASSIFICATION_CONFLICT: "hosts_conflict",
}

# An address is the widest untrusted value a reason is allowed to carry, and 45
# characters is a full IPv6 literal. Anything longer is not an address.
_MAX_REASON_ADDRESS_CHARS = 45
# The width of an agent-authored `error_code`, matching the payload model's own
# bound so a value that fits the wire also fits the row it explains.
_MAX_ERROR_CODE_CHARS = 64

# ── The dispatch lease ────────────────────────────────────────────────────────

# `scan_jobs.dispatch_status`, the half of the lease vocabulary this module
# writes. `running` is the agent's own progress signal and `expired` is Task 23's;
# they are named in `db/models.py` and not restated here.
DISPATCH_STATUS_QUEUED = "queued"
DISPATCH_STATUS_DISPATCHED = "dispatched"
DISPATCH_STATUS_COMPLETED = "completed"
DISPATCH_STATUS_EXECUTION_ERROR = "execution_error"
DISPATCH_STATUS_CANCELLED = "cancelled"

# D-5. How long a job may sit waiting for an agent that is not connected before
# Task 23's reconciliation pass gives it up as `agent_unavailable`. Fifteen
# minutes is three of the agent's own 5-minute reconnect ceilings, so an ordinary
# restart or a brief network partition costs a delay rather than a failed scan.
DISPATCH_DEADLINE_S = int(os.getenv("CB_DISCOVERY_DISPATCH_DEADLINE_S", "900"))

# `scan_jobs.progress_phase` while a claim is parked (D-5). The job stays
# `queued` — `discovery_scheduler._running_scan_count` counts `status ==
# "running"`, and a job that held a scarce slot for the whole deadline while
# doing no work would starve every other scan — so the phase is the only field
# that says what it is waiting for.
PHASE_WAITING_FOR_AGENT = "waiting_for_agent"
PHASE_DISPATCHED = "dispatched"

# The closed `discovery.request` method vocabulary (plan §4), in the agent's own
# spelling: `internal/collect/discover`'s `knownMethods` refuses a request naming
# anything else wholesale, so a name invented here would fail every dispatch.
# All four are always sent: the collectors that are unavailable on a given host
# degrade to a note on the summary rather than to a refusal, and choosing a
# subset here would silently narrow a scan the operator asked for in full.
DISCOVERY_METHODS = ("neighbor_cache", "icmp", "tcp_connect", "reverse_dns")

# The grant's own job budget, used as the request's `deadline_at` and as the
# lease the ingest path judges a late finding against. Read from the registry
# defaults when the grant names nothing usable, never treated as "no deadline":
# a dispatch with no end is one the reconciler can never expire.
_DEFAULT_JOB_TIMEOUT_S = int(_LOCAL_DISCOVERY_DEFAULT_CONFIG["job_timeout_seconds"])
_MIN_JOB_TIMEOUT_S, _MAX_JOB_TIMEOUT_S = _LOCAL_DISCOVERY_BOUNDS["job_timeout_seconds"]

# `discovery_eligibility` denial reasons that mean "not now" rather than "not
# ever" (D-5). Everything else it can answer is a configuration fault that fails
# the job, because retrying it would produce the same answer forever.
_WAITING_REASONS = frozenset(
    {
        discovery_eligibility.REASON_AGENT_OFFLINE,
        discovery_eligibility.REASON_NO_LINK_OWNER,
    }
)

# Every other denial, mapped onto the D-4 vocabulary. An eligibility reason the
# map does not know is `agent_unavailable`: a refusal this module cannot name is
# still a refusal, and failing closed on the vaguest reason is safer than
# dispatching on an unrecognized one.
_ERROR_REASON_FOR_DENIAL = {
    discovery_eligibility.REASON_CAPABILITY_DISABLED: ERROR_CAPABILITY_DISABLED,
    discovery_eligibility.REASON_OUT_OF_SCOPE: ERROR_SCOPE_CHANGED,
}

# ── The terminal summary ──────────────────────────────────────────────────────

# `frame.DiscoveryOutcome*` in the agent's own spelling (`internal/frame/frame.go`),
# and the `scan_jobs.status` each closes the job with. There is no `partial`
# (D-4): `status` is a bare string the history filter, the history query and the
# review badge all read, so an interrupted scan is `failed` with its accepted
# findings kept and reviewable rather than a sixth value every consumer must
# learn.
OUTCOME_COMPLETED = "completed"
OUTCOME_EXECUTION_ERROR = "execution_error"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_REJECTED = "rejected"
STATUS_FOR_OUTCOME = {
    OUTCOME_COMPLETED: "completed",
    OUTCOME_CANCELLED: "cancelled",
    OUTCOME_REJECTED: "failed",
    OUTCOME_EXECUTION_ERROR: "failed",
}
_ERROR_REASON_FOR_OUTCOME = {
    OUTCOME_REJECTED: ERROR_AGENT_REJECTED,
    OUTCOME_EXECUTION_ERROR: ERROR_AGENT_EXECUTION_ERROR,
}
# An outcome a newer agent invented is not permission to close as completed. It
# fails closed onto the same pair an execution error takes, because that is what
# an outcome this server cannot interpret is.
_UNKNOWN_OUTCOME_STATUS = "failed"

# `internal/collect/discover`'s code for the one failure whose counts are real:
# the dispatch's own deadline ran out mid-sweep, and the hosts observed before
# it were still observed. Quoted rather than imported because there is nothing
# to import it from.
ERROR_CODE_DEADLINE_EXCEEDED = "deadline_exceeded"

# What `error_text` says about such a job. A machine-readable marker rather than
# prose, for the reason the whole D-4 vocabulary is: without it the row reads as
# a scan that found two hosts and then simply failed, and an operator has no way
# to tell partial coverage from a fluke.
PARTIAL_RESULTS_NOTE = "partial_results_retained"


class InvalidDiscoveryFinding(ValueError):
    """One rejected `discovery.finding`, carrying the audit trail it belongs in.

    The `agent_link` handler (Task 17) catches this, rate-limits it through
    `agent_telemetry.recordable_violation`, and records `event_type` — so a
    forged dispatch token is auditable as an authorization failure while a
    malformed body stays an ordinary protocol violation.

    `audited` means "this module has already settled the audit trail for this
    rejection; record nothing". Two branches set it, for opposite reasons:

    * the finding-ceiling breach, which also closes the job and therefore has to
      commit its `capability_violation` atomically with that write rather than
      hand it back to a caller that commits afterwards — the handler must skip
      its own `record_event` or the breach records twice; and
    * a finding for a dispatch the *server itself* cancelled, which is not a
      fault at all: the agent was sweeping when the `discovery.cancel` reached
      it and the frames already in its spool are the correct behaviour of a
      correct agent. There is no violation to write, and — because the handler
      returns before `recordable_violation` — no rate-limit window to consume,
      which matters because that window is shared with genuine violations.

    In both cases nothing is written to `scan_results` and the frame is still
    refused; `audited` decides only what the audit trail says about it.
    """

    def __init__(
        self,
        message: str,
        *,
        event_type: str = EVENT_PROTOCOL_VIOLATION,
        audited: bool = False,
    ) -> None:
        super().__init__(message)
        self.event_type = event_type
        self.audited = audited


def _reason(code: str, address: str | None = None) -> str:
    """A rejection reason: a machine-readable code and, at most, an address.

    The address is the only agent-authored value that ever reaches a log line or
    an `agent_events.detail`, and it goes through `safe_log_fragment` on the way
    — a `hostname` field carrying `\\r\\n` plus a forged level prefix is exactly
    the payload plan §7's rule exists for, and the answer is to keep the untrusted
    strings out entirely rather than to escape them.
    """
    if address is None:
        return code
    return f"{code}: {safe_log_fragment(address, _MAX_REASON_ADDRESS_CHARS)}"


def _reject(
    agent_id: int,
    code: str,
    address: str | None = None,
    *,
    event_type: str = EVENT_PROTOCOL_VIOLATION,
    audited: bool = False,
) -> InvalidDiscoveryFinding:
    reason = _reason(code, address)
    # An `audited` refusal is one nobody is being blamed for — see
    # `InvalidDiscoveryFinding` — so it is logged at debug. Warning on it is how
    # an ordinary administrator cancellation comes to look like an incident.
    _logger.log(
        logging.DEBUG if audited else logging.WARNING,
        "agent %s discovery finding rejected: %s",
        agent_id,
        reason,
    )
    return InvalidDiscoveryFinding(reason, event_type=event_type, audited=audited)


def max_findings_per_dispatch(config: Mapping[str, Any] | None) -> int:
    """How many findings one dispatch may produce, from its `local_discovery` grant.

    A missing, non-integer or over-large `max_addresses_per_job` falls back to the
    server's own hard ceiling rather than to "unbounded": the grant is
    administrator input that `agent_capabilities` already validates, so a value
    that fails here is a value that was never written through that path.
    `True` is an `int` and would otherwise configure a one-finding budget.
    """
    raw = (config or {}).get("max_addresses_per_job")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        return MAX_FINDINGS_PER_DISPATCH
    return min(raw, _MAX_ADDRESSES_PER_JOB) + SUMMARY_FINDING_ALLOWANCE


def _dispatch_finding_ceiling(job: ScanJob, config: Mapping[str, Any] | None) -> int:
    """How many findings *this* dispatch may produce — the grant, bounded by the job.

    The grant's `max_addresses_per_job` is a ceiling on any one job, not on this
    one. A job for a /29 covers six usable addresses, and against the grant alone
    an agent could still report ~4100 findings for a single repeated address with
    distinct `finding_id`s, every one of them fanning out through
    `discovery_service._emit_ws_event` to every connected client. The job's own
    `target_cidr` is already the authority for `_in_job_targets`, so it is the
    authority for how many findings those targets can honestly produce too.

    `SUMMARY_FINDING_ALLOWANCE` is added on both sides for the same reason: the
    terminal summary is a frame, and it must not be the one the ceiling refuses.
    A job whose targets parse to nothing gets the bare allowance, which is
    correct — `_in_job_targets` accepts no address for it either.
    """
    return min(
        max_findings_per_dispatch(config),
        agent_scope.address_count(_job_targets(job)) + SUMMARY_FINDING_ALLOWANCE,
    )


def discovery_grant_config(db: Session, agent_id: int) -> dict[str, Any]:
    """The agent's `local_discovery` config, registry defaults merged in.

    Read through `structured_grants_dict` rather than off `grant.config`, for the
    reason `derive_agent_scope` documents: an already-approved agent keeps
    `config = {}` in the database and reads the registry defaults at render time,
    and a migration must never backfill them.
    """
    grant = agent_registry.structured_grants_dict(db, agent_id).get(CAPABILITY) or {}
    config = grant.get("config")
    return config if isinstance(config, dict) else {}


async def dispatch_discovery_job(db: Session, job_id: int) -> bool:
    """Turn one queued agent job into one delivered `discovery.request` (§3, §4).

    Returns whether a request was published. `workers/monitor_probe_dispatch.py`
    is the model; three things differ, each because a discovery lease lives on
    the job row rather than on a row of its own:

    * **The claim is a compare-and-set with a rowcount check.** There is no
      partial unique index to fall back on — `db/models.py` and migration `0100`
      both explain why one over a lease that has only ever one row enforces
      nothing — so the conditional UPDATE *is* the mutual exclusion, and the
      claim is taken before anything awaits so no row lock is held across Redis.
    * **An offline agent parks the job instead of failing it** (D-5). The claim
      is given back — `queued`, `waiting_for_agent`, and a deadline Task 23's
      pass expires — because a job that stayed `running` while it waited would
      hold a concurrency slot for the whole 15 minutes and do no work.
    * **Publication happens after the commit**, unlike `probe.assign`. An agent
      answers a discovery request with findings within milliseconds, and a
      finding that arrives before the lease is committed would be refused as an
      unknown dispatch — which is a `capability_violation` against an agent that
      did exactly what it was told. A frame that then cannot be published closes
      the job as `dispatch_failed`, so the lease is never left open either way.

    Everything between the claim and the publish awaits — `evaluate_eligibility`
    is a real Redis round trip — so the lease is re-asserted against the database
    immediately before the frame goes out, and every write after the claim is
    conditional on this dispatcher still owning the token it minted. Without
    that, a cancellation landing in the await window is overwritten by a
    dispatcher that has no idea it lost the job.

    Owns its commit: it is the top-level caller on this path.
    """
    job = db.execute(select(ScanJob).where(ScanJob.id == job_id)).scalar_one_or_none()
    if job is None or job.scan_agent_id is None:
        _logger.debug("discovery dispatch: job %s is not an agent job", job_id)
        return False
    if job.status != "queued" or job.dispatch_status not in (None, DISPATCH_STATUS_QUEUED):
        # Cancelled, already dispatched, or redelivered. The backend stays
        # authoritative: nothing here may reopen a closed job.
        _logger.debug(
            "discovery dispatch: job %s is %s/%s, not claimable",
            job_id,
            job.status,
            job.dispatch_status,
        )
        return False

    agent_id = job.scan_agent_id
    targets = _job_targets(job)

    # Cardinality, before the lease and not after it. `DiscoveryRequestPayload`
    # caps `targets` at `MAX_DISCOVERY_TARGETS` (plan §4) and
    # `_discovery_request_frame` validates against that model — but it runs after
    # `_claim` has already committed, so an over-cardinality job would take a
    # lease and then die on a pydantic error with the row left `running`.
    # Refusing here closes it with a D-4 reason instead. Creation time asks the
    # same question in `discovery_service.validate_agent_execution_location`;
    # this is the dispatch-time half, because `target_cidr` is an editable column.
    if len(targets) > MAX_DISCOVERY_TARGETS:
        await discovery_service.finalize_agent_job(
            db,
            job,
            "failed",
            error_reason=ERROR_DISPATCH_FAILED,
            error_text=_reason(REASON_TARGET_LIMIT, f"{len(targets)}>{MAX_DISCOVERY_TARGETS}"),
        )
        return False

    scope = derive_discovery_scope(db, agent_id)
    config = discovery_grant_config(db, agent_id)
    deadline_at = utcnow() + timedelta(seconds=_job_timeout_seconds(config))

    dispatch_id = _claim(db, job, scope_version=scope.version, deadline_at=deadline_at)
    if dispatch_id is None:
        return False

    decision = await discovery_eligibility.evaluate_eligibility(
        db,
        agent_id,
        targets=targets,
        tenant_id=job.tenant_id,
        require_online=True,
    )
    if not decision.ok:
        reason = decision.reason or ""
        if reason in _WAITING_REASONS:
            _release_to_waiting(db, job, reason, dispatch_id=dispatch_id)
            return False
        await discovery_service.finalize_agent_job(
            db,
            job,
            "failed",
            error_reason=_ERROR_REASON_FOR_DENIAL.get(reason, ERROR_AGENT_UNAVAILABLE),
            error_text=_reason(reason, decision.detail),
        )
        return False

    # The two limits `discovery_eligibility` deliberately leaves to its callers,
    # re-asked against the *live* grant through the same readers §3's
    # creation-time checkpoint used. An administrator can narrow `tcp_ports` or
    # `max_addresses_per_job` between a profile save and the job it produces.
    nmap_arguments = discovery_service.job_nmap_arguments(db, job)
    requested_ports = discovery_service.granted_tcp_ports(config)
    ungranted = discovery_service.first_ungranted_tcp_port(nmap_arguments, requested_ports)
    if ungranted is not None:
        await discovery_service.finalize_agent_job(
            db,
            job,
            "failed",
            error_reason=ERROR_DISPATCH_FAILED,
            error_text=_reason(discovery_service.REASON_PORT_NOT_GRANTED, str(ungranted)),
        )
        return False

    ceiling = discovery_service.granted_address_ceiling(config)
    count = agent_scope.address_count(targets)
    if count > ceiling:
        await discovery_service.finalize_agent_job(
            db,
            job,
            "failed",
            error_reason=ERROR_DISPATCH_FAILED,
            error_text=_reason(discovery_service.REASON_ADDRESS_LIMIT, f"{count}>{ceiling}"),
        )
        return False

    frame = _discovery_request_frame(
        job,
        dispatch_id=dispatch_id,
        targets=targets,
        tcp_ports=_request_ports(nmap_arguments, requested_ports),
        config=config,
        deadline_at=deadline_at,
    )

    # The last thing before the frame leaves, and a read this dispatcher makes
    # itself rather than a field off an ORM object loaded before three awaits.
    # A cancellation that landed in the await window has already published its
    # `discovery.cancel`; publishing the request now would deliver the two in the
    # wrong order and set the agent sweeping a network whose every finding the
    # ingest path refuses. The row is already terminal, so there is nothing to
    # close here — only a frame not to send.
    if not _lease_still_held(db, job_id, dispatch_id):
        _logger.info(
            "discovery dispatch: job %s lost its lease before publication; nothing was sent",
            job_id,
        )
        return False

    if not await agent_registry.publish_agent_control_frame(agent_id, frame):
        # False means Redis itself was unavailable, so nothing can have arrived.
        # A True with no subscriber is "not guaranteed" rather than "delivered",
        # and that case is the dispatch deadline's, not this branch's.
        _logger.warning("discovery dispatch: job %s could not be published", job_id)
        await discovery_service.finalize_agent_job(
            db, job, "failed", error_reason=ERROR_DISPATCH_FAILED
        )
        return False

    _logger.info(
        "discovery dispatch: job %s dispatched to agent %s (%d addresses)", job_id, agent_id, count
    )
    return True


def _lease_clause(job_id: int, dispatch_id: str) -> list[ColumnElement[bool]]:
    """ "This dispatcher still owns this lease", as one predicate.

    Every post-claim write in `dispatch_discovery_job` is conditional on it, and
    they all have to agree on what ownership means or the guard is decorative.
    The token is the load-bearing half: `dispatch_id` is minted by `_claim` and
    is unique across `scan_jobs`, so matching it proves the row is still the one
    *this* call claimed and not a job somebody else has since re-queued and
    re-dispatched under a new token.
    """
    return [
        ScanJob.id == job_id,
        ScanJob.dispatch_id == dispatch_id,
        ScanJob.dispatch_status == DISPATCH_STATUS_DISPATCHED,
        ScanJob.status == "running",
    ]


def _lease_still_held(db: Session, job_id: int, dispatch_id: str) -> bool:
    """Re-read the lease from the database, not from the identity map.

    A `SELECT` rather than `Session.refresh` so the predicate that decides
    ownership is the one `_lease_clause` states, evaluated by the database on a
    fresh READ COMMITTED snapshot — which is what makes a cancellation another
    connection committed during an `await` visible here.
    """
    held = db.execute(
        select(ScanJob.id).where(*_lease_clause(job_id, dispatch_id))
    ).scalar_one_or_none()
    return held is not None


def _claim(db: Session, job: ScanJob, *, scope_version: str, deadline_at: datetime) -> str | None:
    """Take the lease and return its token, or `None` if somebody else has it.

    The token is returned rather than read back off the job afterwards because
    it is what every later write in this dispatch is guarded on: a caller that
    re-read `job.dispatch_id` would be re-reading a value the very race those
    guards exist for could have moved.

    A compare-and-set rather than a read-then-write: two dispatchers racing one
    job both read `dispatch_status IS NULL`, and only the `WHERE` clause stops
    the second from publishing a second request — two sweeps of the same subnet,
    two terminal summaries, and a second token whose findings the first
    summary's finalization would reject at random.

    `status` moves to `running` here rather than at the first finding, because
    that is what makes the job visible to `_running_scan_count` and therefore
    subject to the same concurrency ceiling as a server scan.
    """
    dispatch_id = secrets.token_hex(16)
    admitted = cast(
        "CursorResult[Any]",
        db.execute(
            update(ScanJob)
            .where(
                ScanJob.id == job.id,
                ScanJob.status == "queued",
                or_(
                    ScanJob.dispatch_status.is_(None),
                    ScanJob.dispatch_status == DISPATCH_STATUS_QUEUED,
                ),
            )
            .values(
                dispatch_id=dispatch_id,
                dispatch_status=DISPATCH_STATUS_DISPATCHED,
                dispatch_deadline_at=deadline_at,
                # D-16: the version in force when the request was built. Ingest
                # judges every finding against this snapshot rather than against
                # a scope the sender could move afterwards, so it has to be
                # written by the same statement that mints the token.
                scope_version=scope_version,
                status="running",
                started_at=utcnow_iso(),
                progress_phase=PHASE_DISPATCHED,
                progress_message="",
                source_type=discovery_service.SOURCE_TYPE_AGENT,
            )
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if not admitted:
        db.rollback()
        _logger.debug("discovery dispatch: job %s was claimed by another dispatcher", job.id)
        return None
    db.commit()
    db.refresh(job)
    return dispatch_id


def _release_to_waiting(db: Session, job: ScanJob, reason: str, *, dispatch_id: str) -> bool:
    """Give the claim back and let the job wait for its agent (D-5).

    `queued`, not `running`: `discovery_scheduler._running_scan_count` counts
    running jobs, and one parked here for the full deadline would starve every
    other scan while doing nothing. `dispatch_id` is cleared with it — a token
    for a request that was never published is one a finding could still quote.

    A compare-and-set for the same reason `finalize_agent_job` is one, and it is
    reached from further away: `evaluate_eligibility` awaits a Redis round trip
    between the claim and this call, and a cancellation committed in that window
    would otherwise be *resurrected* to `queued`/`waiting_for_agent` by a
    dispatcher writing state it read before the await. Returns whether this call
    still owned the lease; a `False` leaves the row exactly as it found it.
    """
    released = cast(
        "CursorResult[Any]",
        db.execute(
            update(ScanJob)
            .where(*_lease_clause(job.id, dispatch_id))
            .values(
                status="queued",
                progress_phase=PHASE_WAITING_FOR_AGENT,
                progress_message="",
                dispatch_status=DISPATCH_STATUS_QUEUED,
                dispatch_id=None,
                scope_version=None,
                started_at=None,
                dispatch_deadline_at=utcnow() + timedelta(seconds=DISPATCH_DEADLINE_S),
            )
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if not released:
        # Cancelled, expired or finalized under us while we were awaiting. The
        # row belongs to whoever took it terminal; parking it would reopen a job
        # the backend has already answered for.
        db.rollback()
        _logger.info(
            "discovery dispatch: job %s was closed while its dispatcher waited; not re-queued",
            job.id,
        )
        return False
    db.commit()
    db.refresh(job)
    _logger.info(
        "discovery dispatch: job %s is waiting for agent %s (%s)",
        job.id,
        job.scan_agent_id,
        safe_log_fragment(reason),
    )
    return True


# ── Cancellation (D-14, D-16) ─────────────────────────────────────────────────
# Five events retire an in-flight dispatch: the job is cancelled through
# `DELETE /discovery/jobs/{id}`, its profile is disabled, the agent's effective
# scope moves under it, the `local_discovery` grant is turned off, or the agent
# is revoked. `monitor_service.ProbeCancellation` / `publish_probe_cancels` is
# the model, and every trigger obeys the same two rules it does:
#
# * **The job is closed in the database first, inside the caller's
#   transaction.** Cancellation is best-effort and the backend is authoritative:
#   a finding for a job this closed is refused by `_assert_dispatch_open`
#   whether or not any `discovery.cancel` was ever delivered. It is also not
#   optional — once the grant is off, `agent_link.dispatch_frame`'s gate drops
#   the agent's own terminal summary as a `capability_violation`, so a dispatch
#   nobody closed here stays open until Task 23's pass expires it.
# * **Nothing is published from inside the transaction.** A trigger builds an
#   inert `DiscoveryCancellation`, commits, and only then hands it to
#   `publish_discovery_cancels` (async callers) or `schedule_discovery_cancels`
#   (synchronous ones). An agent must never be told to abandon a dispatch that a
#   rollback then reinstates.


class DiscoveryCancel(NamedTuple):
    """One retired dispatch, addressed to the agent that still thinks it owns it."""

    agent_id: int
    dispatch_id: str
    job_id: int
    reason: str | None


@dataclass(frozen=True)
class DiscoveryCancellation:
    """What a trigger owes the outside world once its transaction commits.

    Deliberately inert on its own. `job_updates` carries the `job_update`
    payloads the closed rows produce, because these jobs are closed by a bulk
    write rather than by `discovery_service.finalize_agent_job` and would
    otherwise go terminal with no client ever hearing about it.
    """

    cancels: list[DiscoveryCancel] = field(default_factory=list)
    job_updates: list[dict[str, Any]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.cancels or self.job_updates)


class JobCancelOutcome(NamedTuple):
    """Whether *this* call took one job terminal, and what it owes the agent.

    Two facts rather than one, because an empty `DiscoveryCancellation` is
    ambiguous on its own and the caller that has to answer 409 cannot afford the
    ambiguity: a job parked in `waiting_for_agent` (D-5) holds no lease and so
    produces no frame even though this call closed it, while a job that went
    terminal under the caller produces no frame because there was nothing left
    to close. Only the first of those may be followed by a terminal write.
    """

    closed: bool
    cancellation: DiscoveryCancellation


# The job status a server-initiated cancellation writes. Not `failed`: D-4's
# `failed` is for a scan that was interrupted mid-flight, while these jobs were
# taken away by the server before they could finish. `error_reason` is what says
# which of the five triggers took it.
CANCELLED_JOB_STATUS = "cancelled"


def _validated_reason(reason: str | None) -> str | None:
    """D-4's vocabulary is closed. A reason outside it is a programming error
    here, not a value to persist: `scan_jobs.error_reason` is read by the
    frontend's history filter and by the audit trail, and neither may be shown a
    string this module invented."""
    if reason is not None and reason not in JOB_ERROR_REASONS:
        raise ValueError(f"{reason!r} is not a scan job error reason")
    return reason


def _open_agent_jobs(
    db: Session, *, agent_id: int | None = None, profile_id: int | None = None
) -> list[ScanJob]:
    """Every unfinished agent job matching the filter, oldest first.

    `queued` is included alongside `running`: a job parked in
    `waiting_for_agent` (D-5) holds no lease, but its agent will never run it
    once the grant is off or the profile is disabled, and leaving it queued
    would have Task 23's pass dispatch it later.
    """
    stmt = select(ScanJob).where(
        ScanJob.scan_agent_id.is_not(None),
        ScanJob.status.in_(sorted(_OPEN_JOB_STATUSES)),
    )
    if agent_id is not None:
        stmt = stmt.where(ScanJob.scan_agent_id == agent_id)
    if profile_id is not None:
        stmt = stmt.where(ScanJob.profile_id == profile_id)
    return list(db.execute(stmt.order_by(ScanJob.id)).scalars().all())


def _transition_terminal(
    db: Session,
    job: ScanJob,
    status: str,
    *,
    error_reason: str | None = None,
    error_text: str | None = None,
    progress_message: str = "",
    closed_at: str,
) -> bool:
    """Move one agent job to a terminal state, or report it was already there.

    The one compare-and-set every terminal transition this module makes goes
    through — the cancellation triggers and the finding-ceiling breach alike —
    and the reason there is only one: `_open_agent_jobs` SELECTs and the caller
    writes, and in between `finalize_agent_job` can accept the agent's terminal
    summary on the `/link` connection. A blind write then turns a scan that
    *completed* into one that was cancelled and emits a `discovery.cancel` for
    work that already finished. The predicate is `finalize_agent_job`'s own —
    `status IN ('queued','running')` — so no two writers of a terminal
    `scan_jobs.status` can disagree about which rows are still open.

    Deliberately does not commit and does not emit: the cancellation callers have
    to land in the same transaction as the grant edit, profile edit or network
    report that caused it and publish only after that commits, and the ceiling
    breach has to commit its audit row atomically with this write.

    On success the ORM object is brought back in step with the row, because the
    statement runs with `synchronize_session=False` and the caller reads `job`
    afterwards.
    """
    values: dict[str, Any] = {
        "status": status,
        "completed_at": closed_at,
        "dispatch_status": discovery_service._DISPATCH_STATUS_FOR_JOB_STATUS[status],
        "progress_phase": discovery_service._PROGRESS_PHASE_FOR_JOB_STATUS[status],
        "progress_message": progress_message,
    }
    # Left untouched rather than nulled when unnamed: a cancellation an operator
    # asked for is not one of D-4's error outcomes, and the status alone says so.
    if error_reason is not None:
        values["error_reason"] = error_reason
    if error_text is not None:
        values["error_text"] = error_text
    transitioned = cast(
        "CursorResult[Any]",
        db.execute(
            update(ScanJob)
            .where(ScanJob.id == job.id, ScanJob.status.in_(sorted(_OPEN_JOB_STATUSES)))
            .values(**values)
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if not transitioned:
        _logger.debug("discovery job %s was already terminal; this write is inert", job.id)
        return False
    for column, value in values.items():
        setattr(job, column, value)
    return True


def _close_jobs(db: Session, jobs: list[ScanJob], reason: str | None) -> DiscoveryCancellation:
    """Retire *jobs* and their leases. Caller owns the transaction.

    Written through `_transition_terminal` rather than through
    `finalize_agent_job`: that one owns its own commit and emits its own events,
    and every trigger here has to land in the same transaction as the grant edit,
    profile edit or network report that caused it. What the two *do* share is the
    compare-and-set, so a job that finished between the SELECT and this write
    keeps its own outcome — and produces neither a `discovery.cancel` nor a
    `job_update` contradicting it.
    """
    cancels: list[DiscoveryCancel] = []
    updates: list[dict[str, Any]] = []
    closed_at = utcnow_iso()
    for job in jobs:
        if not _transition_terminal(
            db,
            job,
            CANCELLED_JOB_STATUS,
            error_reason=reason,
            error_text=reason,
            closed_at=closed_at,
        ):
            continue
        updates.append(
            {
                "job": {
                    "id": job.id,
                    "status": CANCELLED_JOB_STATUS,
                    "error_reason": reason,
                    "progress_percent": 100,
                }
            }
        )
        # No lease means nothing was ever published under a token the agent
        # could quote, so there is nothing to tell it about.
        if job.dispatch_id is not None and job.scan_agent_id is not None:
            cancels.append(DiscoveryCancel(job.scan_agent_id, job.dispatch_id, job.id, reason))
        _logger.info(
            "discovery job %s cancelled for agent %s (%s)",
            job.id,
            job.scan_agent_id,
            safe_log_fragment(reason or CANCELLED_JOB_STATUS),
        )
    return DiscoveryCancellation(cancels=cancels, job_updates=updates)


def cancel_agent_dispatches(
    db: Session, agent_id: int, *, reason: str | None = None
) -> DiscoveryCancellation:
    """Retire every dispatch this agent holds (D-14). Caller owns the transaction.

    The trigger for `local_discovery` being turned off and for revocation, and
    the one Task 23 and `agent_link` reach for when an agent goes away for good.
    """
    return _close_jobs(db, _open_agent_jobs(db, agent_id=agent_id), _validated_reason(reason))


def cancel_profile_dispatches(
    db: Session, profile_id: int, *, reason: str = ERROR_PROFILE_DISABLED
) -> DiscoveryCancellation:
    """Retire whatever this profile has in flight (D-14). Caller owns the transaction.

    Two callers, deliberately one implementation:
    `discovery_profiles_service.update_profile` when an administrator disables a
    profile, and Task 24's subnet-disappearance path — which disables the system
    profile for a subnet the agent stopped reporting. D-14 names profile-disable
    as the trigger an implementation forgets, and those are the two places it
    happens.
    """
    return _close_jobs(db, _open_agent_jobs(db, profile_id=profile_id), _validated_reason(reason))


def cancel_job_dispatch(
    db: Session, job: ScanJob, *, reason: str | None = None
) -> JobCancelOutcome:
    """Close one agent job and retire the lease it holds, if it holds one.
    Caller owns the transaction.

    Narrower than the helpers above on purpose: `DELETE /discovery/jobs/{id}`
    emits its own `job_update` — it has to, because it serves server jobs too —
    so this writes the terminal status, closes the lease and produces the frame,
    and nothing else. A job with no `scan_agent_id` is a server scan and there is
    nothing here to do.

    The write is the same compare-and-set `_close_jobs` uses, for the same
    reason: the caller read this row before it decided to cancel, and a summary
    accepted on the `/link` connection in between must not be overwritten. This
    is the *only* terminal write the endpoint makes for an agent job — it used
    to follow this call with a blind `job.status = "cancelled"`, which turned a
    scan that had just completed into a cancelled one whose `dispatch_status`
    still said `completed`. `closed` is what the endpoint answers 409 on, and it
    is reported separately from the cancellation because a closed job with no
    lease produces no frame either.
    """
    _validated_reason(reason)
    if job.scan_agent_id is None or job.status not in _OPEN_JOB_STATUSES:
        return JobCancelOutcome(False, DiscoveryCancellation())
    # The token is read before the write, because a successful transition
    # rewrites the row and the frame has to quote the lease that was open.
    dispatch_id = job.dispatch_id
    if not _transition_terminal(
        db,
        job,
        CANCELLED_JOB_STATUS,
        error_reason=reason,
        error_text=reason,
        closed_at=utcnow_iso(),
    ):
        return JobCancelOutcome(False, DiscoveryCancellation())
    if dispatch_id is None:
        return JobCancelOutcome(True, DiscoveryCancellation())
    return JobCancelOutcome(
        True,
        DiscoveryCancellation(
            cancels=[DiscoveryCancel(job.scan_agent_id, dispatch_id, job.id, reason)]
        ),
    )


def cancel_scope_changed_dispatches(db: Session, agent_id: int) -> DiscoveryCancellation:
    """Retire the dispatches this agent's *current* scope no longer authorizes (D-16).

    Fired from the two places a scope can move: `agent_registry.
    record_network_facts` reporting a real change — the agent gained or lost an
    interface — and an administrator editing the grant's `scope_mode`,
    `excluded_cidrs` or `additional_cidrs`. Both funnel here rather than each
    deciding for itself which jobs are still authorized, because a scope
    evaluated twice is a scope evaluated two ways.

    Caller owns the transaction.
    """
    scope = derive_discovery_scope(db, agent_id)
    doomed = [
        job for job in _open_agent_jobs(db, agent_id=agent_id) if _scope_moved_under(job, scope)
    ]
    return _close_jobs(db, doomed, ERROR_SCOPE_CHANGED)


def _scope_moved_under(job: ScanJob, scope: agent_scope.EffectiveScope) -> bool:
    """Is this job's authorization gone — either of the two ways it can go?

    A **live** dispatch is judged on its snapshot: `job.scope_version` is the
    version that was in force when its request was built, and the ingest path
    refuses every finding arriving under any other one (D-16), so a dispatch
    whose version has moved can only starve. Its targets are not re-checked,
    because the version already covers them.

    A job with no lease — parked in `waiting_for_agent` (D-5), or queued and
    never claimed — has no snapshot to compare and must survive a scope that
    moved without touching it. It is judged on containment alone: cancelling it
    for a change it still fits would fail a scan that is perfectly authorized,
    and the dispatcher re-derives the version when it eventually claims it.
    """
    if job.dispatch_id is not None:
        return job.scope_version != scope.version
    return any(
        not agent_scope.network_in_scope(scope, target).allowed for target in _job_targets(job)
    )


async def publish_discovery_cancels(cancellation: DiscoveryCancellation) -> int:
    """Tell the agents, and refresh the job cards. Returns the frames published.

    Never raises. `publish_agent_control_frame` already swallows a dead Redis,
    but the guard is explicit here because every caller is an administrator
    action — a grant edit, a profile edit, a revoke — and an agent that vanished
    must not turn one of those into a 500. The rows are already closed by the
    time this runs, so an undelivered cancel costs the agent one wasted sweep
    whose findings are refused on arrival, and costs the backend nothing.
    """
    delivered = 0
    for cancel in cancellation.cancels:
        payload = {"dispatch_id": cancel.dispatch_id, "reason": cancel.reason}
        DiscoveryCancelPayload.model_validate(payload)
        try:
            published = await agent_registry.publish_agent_control_frame(
                cancel.agent_id, {"type": TYPE_DISCOVERY_CANCEL, "payload": payload}
            )
        except Exception:  # noqa: BLE001
            _logger.warning(
                "discovery cancel for job %s could not be published", cancel.job_id, exc_info=True
            )
            continue
        delivered += 1 if published else 0
    for job_update in cancellation.job_updates:
        try:
            await discovery_service._emit_ws_event("job_update", job_update)
        except Exception:  # noqa: BLE001
            _logger.debug("discovery cancel job_update could not be emitted", exc_info=True)
    return delivered


def schedule_discovery_cancels(cancellation: DiscoveryCancellation) -> bool:
    """The synchronous callers' half of `publish_discovery_cancels`.

    Borrows `monitor_service._publish_soon` rather than restating the
    `get_running_loop()` + `create_task` idiom, which that function's own
    docstring calls its single home — so a discovery cancellation and a probe
    cancellation behave identically when there is no loop to publish on.
    Imported inside the function because that module is a large one this
    service otherwise has no need of.
    """
    if not cancellation:
        return False
    from app.services.monitor_service import _publish_soon

    return _publish_soon("discovery cancellations", lambda: publish_discovery_cancels(cancellation))


def _job_targets(job: ScanJob) -> list[str]:
    """The prefixes this job asked for, in the form the scope evaluator takes."""
    return [part.strip() for part in (job.target_cidr or "").split(",") if part.strip()]


def _job_timeout_seconds(config: Mapping[str, Any]) -> int:
    """The grant's per-job budget, clamped to the bounds `agent_capabilities`
    validates against. A missing or nonsensical value means the documented
    default, never "no deadline": a dispatch with no end is one the reconciler
    can never expire and the ingest path can never refuse a late finding for."""
    raw = config.get("job_timeout_seconds")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return _DEFAULT_JOB_TIMEOUT_S
    return max(_MIN_JOB_TIMEOUT_S, min(raw, _MAX_JOB_TIMEOUT_S))


def _request_ports(nmap_arguments: str | None, granted: frozenset[int]) -> list[int]:
    """The ports this request asks the agent to open.

    A job that named its own `-p` spec gets exactly those — an operator who
    asked for two ports should not have nine swept — and every one of them is
    already known to be inside *granted*, because the caller refused the request
    otherwise. A job that named none gets the grant's list, which is what the
    agent would clamp to anyway.
    """
    requested = discovery_service.requested_tcp_ports(nmap_arguments, granted)
    return sorted(requested) if requested else sorted(granted)


def _discovery_request_frame(
    job: ScanJob,
    *,
    dispatch_id: str,
    targets: list[str],
    tcp_ports: list[int],
    config: Mapping[str, Any],
    deadline_at: datetime,
) -> dict[str, Any]:
    """The wire frame, validated against the contract before it is published.

    Datetimes are `.isoformat()`, never the raw value:
    `publish_agent_control_frame` serializes with `json.dumps(default=str)`,
    which renders a datetime as "2026-08-08 18:00:00+00:00" — a space separator
    Go's `time.Time` rejects outright. `monitor_probe_dispatch` carries the same
    note at its own `scheduled_at`.

    The payload is round-tripped through `DiscoveryRequestPayload` rather than
    trusted: it is the model both languages share, and a field this side widened
    past a bound the agent enforces would otherwise be discovered by the agent
    refusing every dispatch.

    `dispatch_id` is the token `_claim` returned rather than `job.dispatch_id`:
    the frame must quote the lease this dispatcher minted, not whatever the row
    happens to hold by the time the frame is built.
    """
    payload = {
        "dispatch_id": dispatch_id,
        "scan_job_id": job.id,
        "targets": targets,
        "methods": list(DISCOVERY_METHODS),
        "tcp_ports": tcp_ports,
        "host_timeout_ms": int(config.get("host_timeout_ms") or 0)
        or int(_LOCAL_DISCOVERY_DEFAULT_CONFIG["host_timeout_ms"]),
        "max_concurrent_hosts": int(config.get("max_concurrent_hosts") or 0)
        or int(_LOCAL_DISCOVERY_DEFAULT_CONFIG["max_concurrent_hosts"]),
        "scope_version": job.scope_version,
        "deadline_at": deadline_at.isoformat(),
    }
    DiscoveryRequestPayload.model_validate(payload)
    return {"type": TYPE_DISCOVERY_REQUEST, "payload": payload}


def validate_finding_payload(payload: dict[str, Any]) -> DiscoveryFindingPayload:
    """Size limit, then schema, then the `kind` vocabulary — in that order.

    The size check runs against the raw mapping rather than the parsed model on
    purpose: parsing a hostile 40 MiB body to find out it is too big is the cost
    this is meant to avoid.
    """
    if not isinstance(payload, dict):
        raise InvalidDiscoveryFinding("payload is not an object")

    try:
        encoded = json.dumps(payload, separators=(",", ":"), default=str).encode()
    except (TypeError, ValueError) as exc:
        raise InvalidDiscoveryFinding("payload is not serializable") from exc
    if len(encoded) > MAX_FINDING_BYTES:
        raise InvalidDiscoveryFinding(f"finding exceeds {MAX_FINDING_BYTES} bytes")

    try:
        finding = DiscoveryFindingPayload.model_validate(payload)
    except ValidationError as exc:
        # The message is deliberately not `str(exc)`: pydantic echoes the
        # offending input, which for `hostname` or `banner` is attacker-authored
        # text plan §7 forbids in an audit detail.
        raise InvalidDiscoveryFinding("payload schema is invalid") from exc

    if finding.kind not in DISCOVERY_KINDS:
        raise InvalidDiscoveryFinding(f"unsupported finding kind {safe_log_fragment(finding.kind)}")
    return finding


async def ingest_discovery_finding(
    db: Session,
    agent: Agent,
    payload: dict[str, Any],
    *,
    received_at: datetime | None = None,
) -> str:
    """Accept, refuse or ignore one `discovery.finding`. Returns the disposition.

    `received_at` exists so tests can pin the lease rule; production callers omit
    it and get the server's own clock, which is the whole point — see the module
    docstring on why `frame.ts` must never be used here.

    Owns its commit on every branch that writes, so a rejected frame leaves the
    session exactly as it found it and the caller's `record_event` is the only
    thing left to persist.
    """
    if agent.status != "active":
        raise _reject(agent.id, REASON_AGENT_INACTIVE)

    finding = validate_finding_payload(payload)
    job = _authenticated_job(db, agent, finding)
    is_summary = finding.kind == DISCOVERY_KIND_SUMMARY
    closed = _assert_dispatch_open(agent, job, received_at, is_summary=is_summary)
    if closed is not None:
        return closed

    if is_summary:
        # Everything a summary shares with a host finding has now run.
        return await _finalize_from_summary(db, job, finding)

    # The grant and the scope it derives, resolved once for this frame and passed
    # down. They used to be read twice — `_authorized_address` derived the scope
    # (a grant read plus an `agent_networks` read) and `_record_host_finding`
    # read the grant again for the ceiling — which is three round trips per
    # finding on the path the module docstring promises is "a handful of indexed
    # lookups". Resolving here keeps the security properties identical: the D-16
    # check below still compares the freshly derived version against
    # `job.scope_version`, and nothing is cached across findings.
    config = discovery_grant_config(db, agent.id)
    scope = derive_discovery_scope(db, agent.id, config)
    address = _authorized_address(agent, job, finding, scope)
    return await _record_host_finding(
        db, agent, job, finding, address, ceiling=_dispatch_finding_ceiling(job, config)
    )


async def _finalize_from_summary(
    db: Session, job: ScanJob, finding: DiscoveryFindingPayload
) -> str:
    """Close the dispatch the terminal summary belongs to.

    The summary's own `hosts_found`/`addresses_scanned` are the agent's tally
    and are deliberately *not* written to the job: D-10 makes the agent path's
    counters incremental, accumulated per accepted finding inside the ingest
    transaction, and the terminal frame is the one place a stale or optimistic
    agent count could silently replace what the server actually accepted. They
    are logged when they disagree, because a persistent gap is a real signal —
    findings the server refused, or a spool that never drained.

    Idempotency is `finalize_agent_job`'s compare-and-set, not a pre-check here:
    two replays of one summary racing on separate connections both pass the
    dispatch-open guard above, and only the conditional UPDATE admits one.
    """
    outcome = finding.outcome or ""
    status = STATUS_FOR_OUTCOME.get(outcome, _UNKNOWN_OUTCOME_STATUS)
    error_reason = (
        None
        if status == "completed" or status == "cancelled"
        else _ERROR_REASON_FOR_OUTCOME.get(outcome, ERROR_AGENT_EXECUTION_ERROR)
    )

    if finding.hosts_found is not None and finding.hosts_found != (job.hosts_found or 0):
        _logger.info(
            "agent %s reported %d hosts for job %s but %d findings were accepted",
            job.scan_agent_id,
            finding.hosts_found,
            job.id,
            job.hosts_found or 0,
        )

    await discovery_service.finalize_agent_job(
        db,
        job,
        status,
        error_reason=error_reason,
        error_text=_summary_error_text(job, error_reason, finding.error_code),
    )
    return DISPOSITION_SUMMARY


def _summary_error_text(
    job: ScanJob, error_reason: str | None, error_code: str | None
) -> str | None:
    """The human-and-machine readable half of a failed agent job.

    `error_code` is agent-authored, so it goes through `safe_log_fragment` on
    the way in exactly as a rejection reason's address does — `error_text` is
    rendered in the UI and read back out of the row, and a value carrying
    `\\r\\n` would forge a second line in both.

    A `deadline_exceeded` job gets the extra marker, because its counts are
    real: the agent swept part of the target and the hosts it found are kept and
    reviewable. D-4 gives that no status of its own, so this is the only place
    the row can say that its coverage is partial rather than absent.
    """
    if error_reason is None:
        return None
    parts = [error_reason]
    if error_code:
        parts.append(safe_log_fragment(error_code, _MAX_ERROR_CODE_CHARS))
    if error_code == ERROR_CODE_DEADLINE_EXCEEDED:
        parts.append(f"{PARTIAL_RESULTS_NOTE}={job.finding_count or 0}")
    return ": ".join(parts[:2]) + ("; " + parts[2] if len(parts) > 2 else "")


def _authenticated_job(db: Session, agent: Agent, finding: DiscoveryFindingPayload) -> ScanJob:
    """The (dispatch, job, agent, tenant) quadruple, matched before anything is written."""
    job = db.execute(
        select(ScanJob).where(ScanJob.dispatch_id == finding.dispatch_id)
    ).scalar_one_or_none()
    if job is None:
        raise _reject(agent.id, REASON_UNKNOWN_DISPATCH, event_type=EVENT_CAPABILITY_VIOLATION)
    if job.scan_agent_id != agent.id:
        raise _reject(
            agent.id, REASON_DISPATCH_OWNER_MISMATCH, event_type=EVENT_CAPABILITY_VIOLATION
        )
    if job.id != finding.scan_job_id:
        raise _reject(agent.id, REASON_DISPATCH_JOB_MISMATCH, event_type=EVENT_CAPABILITY_VIOLATION)
    if job.tenant_id != agent.tenant_id:
        # Plan §8: tenant context is derived from the job/agent, never accepted
        # from a finding. A job whose tenant has drifted from the reporting
        # agent's is not one this agent may write into, whatever token it holds.
        raise _reject(agent.id, REASON_TENANT_MISMATCH, event_type=EVENT_CAPABILITY_VIOLATION)
    return job


def _assert_dispatch_open(
    agent: Agent, job: ScanJob, received_at: datetime | None, *, is_summary: bool
) -> str | None:
    """`None` while the dispatch is open; a disposition for the one closed case
    that is an expected frame; raises for every other closed dispatch.

    **A cancellation is not a violation.** The frame that most reliably arrives
    for a cancelled dispatch is the agent's *correct* answer to the server's own
    `discovery.cancel`: `runtime.execute` overrides whatever the interrupted
    sweep produced with a terminal summary carrying `outcome="cancelled"`. That
    one is a no-op with a disposition of its own — the agent did exactly what it
    was told, and there is nothing to refuse it for.

    Host findings for the same dispatch are still refused, because the server
    has called the work off and will write none of them — but they are refused
    `audited`, so nothing is recorded against the agent. They are the frames the
    sweep had already emitted when the cancel reached it, which is likewise the
    behaviour of a correct agent. Before this, every ordinary administrator
    cancellation wrote a `protocol_violation` for each of them and consumed the
    one-per-minute window that genuine violations share.

    Both columns are read because both move independently: `DELETE
    /discovery/jobs/{id}` cancels the job, `_close_jobs` cancels the lease.
    """
    if job.dispatch_status == DISPATCH_STATUS_CANCELLED or job.status == CANCELLED_JOB_STATUS:
        if is_summary:
            _logger.debug(
                "agent %s closed cancelled dispatch for job %s; nothing to do", agent.id, job.id
            )
            return DISPOSITION_CANCELLED
        raise _reject(
            agent.id, REASON_DISPATCH_CLOSED, job.dispatch_status or job.status, audited=True
        )

    if job.dispatch_status not in _OPEN_DISPATCH_STATUSES or job.status not in _OPEN_JOB_STATUSES:
        raise _reject(agent.id, REASON_DISPATCH_CLOSED, job.dispatch_status or job.status)

    now = _aware(received_at) if received_at is not None else utcnow()
    deadline = job.dispatch_deadline_at
    if deadline is not None and now > _aware(deadline) + LATE_FINDING_GRACE:
        raise _reject(agent.id, REASON_LATE_FINDING)
    return None


def _authorized_address(
    agent: Agent,
    job: ScanJob,
    finding: DiscoveryFindingPayload,
    scope: agent_scope.EffectiveScope,
) -> str:
    """The finding's address, proven to be inside both the job's targets and its scope.

    *scope* is derived by the caller once per frame and is the agent's **live**
    scope, exactly as before — the D-16 rule below is what makes that safe, and
    it is a version comparison against the job rather than trust in the scope
    itself.
    """
    if not finding.ip_address:
        # `scan_results.ip_address` is NOT NULL, so an addressless host finding
        # would otherwise be an IntegrityError inside the `/link` read loop.
        raise _reject(agent.id, REASON_MISSING_ADDRESS)
    address = discovery_result_service.normalize_ip(finding.ip_address) or finding.ip_address

    if not _in_job_targets(job, address):
        raise _reject(
            agent.id, REASON_OUT_OF_TARGET, address, event_type=EVENT_CAPABILITY_VIOLATION
        )

    if scope.version != job.scope_version:
        # D-16. The live scope is not the authority: a sender that can move its
        # own scope between dispatch and ingest would otherwise widen what it may
        # report about. Refusing on a version mismatch is what makes the check
        # "against the scope snapshotted on the job" rather than against one the
        # sender controls; Task 22 cancels the dispatch on the same signal.
        raise _reject(agent.id, ERROR_SCOPE_CHANGED, address, event_type=EVENT_CAPABILITY_VIOLATION)

    decision = agent_scope.evaluate(scope, address)
    if not decision.allowed:
        raise _reject(agent.id, decision.reason, address, event_type=EVENT_CAPABILITY_VIOLATION)
    return address


def _in_job_targets(job: ScanJob, address: str) -> bool:
    """Is *address* inside one of the prefixes this dispatch actually asked for?

    A job with no targets matches nothing rather than everything: `target_cidr`
    is what the dispatcher validated and shipped, and an empty one means there is
    nothing an agent could legitimately be reporting on.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    for target in (job.target_cidr or "").split(","):
        target = target.strip()
        if not target:
            continue
        try:
            if parsed in ipaddress.ip_network(target, strict=False):
                return True
        except ValueError:
            # A malformed stored target authorizes nothing; it cannot be the
            # thing that decides an address is acceptable.
            continue
    return False


async def _record_host_finding(
    db: Session,
    agent: Agent,
    job: ScanJob,
    finding: DiscoveryFindingPayload,
    address: str,
    *,
    ceiling: int,
) -> str:
    """Insert, count, commit, publish — in that order, and only all four together.

    The insert runs inside a SAVEPOINT because `uq_scan_results_job_finding` is
    the idempotency key and a pre-check is not one: two spool replays racing on
    separate connections both pass a `SELECT`. The ceiling is a compare-and-set
    on the same statement that increments the counters, for the same reason, and
    it is passed in rather than re-derived so the grant is read once per frame.
    """
    savepoint = db.begin_nested()
    try:
        result, classification = discovery_result_service.build_and_classify_result(
            db,
            job,
            _raw_result(agent, job, finding, address),
            discovery_agent_id=agent.id,
            finding_id=finding.finding_id,
        )
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        # A replayed finding is inert by design: no second row, no second
        # counter increment, and — because this returns before the publish
        # below — no second `result_added` fanned out to every client.
        _logger.debug(
            "agent %s replayed finding %s for job %s", agent.id, finding.finding_id, job.id
        )
        return DISPOSITION_DUPLICATE

    counter = _COUNTER_FOR_CLASSIFICATION[classification]
    admitted = cast(
        "CursorResult[Any]",
        db.execute(
            update(ScanJob)
            .where(ScanJob.id == job.id, ScanJob.finding_count < ceiling)
            .values(
                {
                    "finding_count": ScanJob.finding_count + 1,
                    "hosts_found": func.coalesce(ScanJob.hosts_found, 0) + 1,
                    counter: func.coalesce(getattr(ScanJob, counter), 0) + 1,
                    "last_finding_at": utcnow(),
                }
            )
            .execution_options(synchronize_session=False)
        ),
    ).rowcount
    if not admitted:
        # Rolls the insert back with it, so the N+1th finding buys the agent
        # nothing at all: no row, no counter, no event.
        savepoint.rollback()
        await _close_over_ceiling(db, agent, job, ceiling)
        raise InvalidDiscoveryFinding(
            _reason(REASON_FINDING_CEILING, str(ceiling)),
            event_type=EVENT_CAPABILITY_VIOLATION,
            audited=True,
        )
    savepoint.commit()

    payload = ScanResultOut.model_validate(result).model_dump()
    db.commit()
    # After the commit, never before: a client that fetched the job on this
    # event must find the row already there.
    _logger.debug(
        "agent %s discovery finding %s accepted for job %s (%s)",
        agent.id,
        finding.finding_id,
        job.id,
        classification,
    )
    await discovery_service._emit_ws_event("result_added", {"job_id": job.id, "result": payload})
    return DISPOSITION_ACCEPTED


async def _close_over_ceiling(db: Session, agent: Agent, job: ScanJob, ceiling: int) -> None:
    """Close the job, audit the breach, then tell the clients watching it.

    D-4's `agent_execution_error`: an agent producing more findings than its own
    address budget allows is not executing the job it was given. Task 21's
    `finalize_agent_job` owns the ordinary terminal path and its events; this one
    writes the columns directly because it must land in the same transaction as
    the `capability_violation` that explains it — which is also why the exception
    raised afterwards is marked `audited`.

    It still owes the same two events every other terminal writer emits. Without
    them a client watching this job sees it stop at whatever percentage it had
    reached and never learns it failed, because the frame that closed it is
    refused rather than acknowledged and nothing else on this path speaks to the
    browser. Emitted after the commit, never before, for `finalize_agent_job`'s
    reason: a client that refetches on the event must find the row terminal.
    """
    error_text = _reason(REASON_FINDING_CEILING, str(ceiling))
    # Through the same compare-and-set the cancellation triggers use, not a
    # column-by-column write: the agent's own terminal summary can be accepted on
    # another connection between the ceiling check above and this write, and a
    # blind one would turn a completed scan into an execution error.
    closed_here = _transition_terminal(
        db,
        job,
        "failed",
        error_reason=ERROR_AGENT_EXECUTION_ERROR,
        error_text=error_text,
        progress_message=error_text,
        closed_at=utcnow_iso(),
    )
    # The breach is audited whether or not this call is the one that closed the
    # job: the agent still sent a finding past its budget, and that is the fact
    # `capability_violation` records.
    record, count = agent_telemetry.recordable_violation(agent.id)
    if record:
        agent_registry.record_event(
            db,
            agent.id,
            EVENT_CAPABILITY_VIOLATION,
            detail={"reason": error_text, "scan_job_id": job.id, "repeated": count},
        )
    db.commit()

    if not closed_here:
        # Somebody else closed it and emitted for it; a second terminal pair
        # would contradict whatever outcome they wrote.
        return

    pending_count = db.query(ScanResult).filter(ScanResult.merge_status == "pending").count()
    await discovery_service._emit_ws_event(
        "job_update",
        {
            "job": {
                "id": job.id,
                "status": "failed",
                "error_reason": ERROR_AGENT_EXECUTION_ERROR,
                "progress_percent": 100,
            },
            "pending_count": pending_count,
        },
    )
    await discovery_service._emit_ws_event(
        "job_progress",
        {
            "job_id": job.id,
            "phase": discovery_service._PROGRESS_PHASE_FOR_JOB_STATUS["failed"],
            "message": error_text,
            "percent": 100,
        },
    )


def _raw_result(
    agent: Agent, job: ScanJob, finding: DiscoveryFindingPayload, address: str
) -> dict[str, Any]:
    """The finding, in the raw shape `discovery_result_service` already speaks.

    `evidence` rides in `raw_nmap_xml` rather than in any projected column: that
    is the one field `ScanResultOut` deliberately never includes
    (`schemas/discovery.py`), so agent-authored free text stays out of the
    `result_added` frame and out of every API response while remaining available
    to an operator debugging a dispatch.
    """
    banner = next((p.banner for p in finding.open_ports if p.banner), None)
    return {
        "ip": address,
        "mac_address": finding.mac_address,
        "hostname": finding.hostname,
        "banner": banner,
        # A list, not a JSON string: `inference_service._infer_from_ports`
        # iterates it expecting dicts.
        "open_ports_json": [
            {
                "port": p.port,
                "protocol": p.protocol,
                "service": PORT_SERVICE_MAP.get(p.port, {}).get("name", "unknown"),
                "state": "open",
            }
            for p in finding.open_ports
        ]
        or None,
        "source": "agent",
        "source_type": "agent",
        "snmp_data": {},
        "raw_nmap_xml": json.dumps(
            {
                "source": "agent",
                "agent_id": agent.id,
                "dispatch_id": job.dispatch_id,
                "finding_id": finding.finding_id,
                "observed_at": finding.observed_at.isoformat(),
                "evidence": list(finding.evidence),
            }
        ),
    }


def _aware(value: datetime) -> datetime:
    """`scan_jobs` admits naive datetimes; comparing one against a tz-aware clock
    would raise inside the /link read loop and take the connection down over a
    cosmetic serialization difference."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "CANCELLED_JOB_STATUS",
    "DISCOVERY_METHODS",
    "DISPATCH_DEADLINE_S",
    "DISPATCH_STATUS_CANCELLED",
    "DISPATCH_STATUS_COMPLETED",
    "DISPATCH_STATUS_DISPATCHED",
    "DISPATCH_STATUS_EXECUTION_ERROR",
    "DISPATCH_STATUS_QUEUED",
    "DISPOSITION_ACCEPTED",
    "DISPOSITION_CANCELLED",
    "DISPOSITION_DUPLICATE",
    "DISPOSITION_SUMMARY",
    "ERROR_AGENT_DISCONNECTED",
    "ERROR_AGENT_EXECUTION_ERROR",
    "ERROR_AGENT_REJECTED",
    "ERROR_AGENT_UNAVAILABLE",
    "ERROR_CAPABILITY_DISABLED",
    "ERROR_CODE_DEADLINE_EXCEEDED",
    "ERROR_DISPATCH_FAILED",
    "ERROR_PROFILE_DISABLED",
    "ERROR_SCOPE_CHANGED",
    "JOB_ERROR_REASONS",
    "LATE_FINDING_GRACE",
    "MAX_FINDINGS_PER_DISPATCH",
    "MAX_FINDING_BYTES",
    "PARTIAL_RESULTS_NOTE",
    "PHASE_DISPATCHED",
    "PHASE_WAITING_FOR_AGENT",
    "REASON_TARGET_LIMIT",
    "STATUS_FOR_OUTCOME",
    "SUMMARY_FINDING_ALLOWANCE",
    "DiscoveryCancel",
    "DiscoveryCancellation",
    "InvalidDiscoveryFinding",
    "JobCancelOutcome",
    "cancel_agent_dispatches",
    "cancel_job_dispatch",
    "cancel_profile_dispatches",
    "cancel_scope_changed_dispatches",
    "dispatch_discovery_job",
    "discovery_grant_config",
    "ingest_discovery_finding",
    "max_findings_per_dispatch",
    "publish_discovery_cancels",
    "schedule_discovery_cancels",
    "validate_finding_payload",
]
