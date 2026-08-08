"""`discovery.finding` ingest — the one surface a remote agent can write discovery rows from (§4).

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
6. **A ceiling on how many findings one dispatch may produce.** Derived from the
   agent's own `max_addresses_per_job` grant plus a small summary allowance, and
   enforced as a compare-and-set on `scan_jobs.finding_count` so two concurrent
   ingests cannot both squeeze past it. Without it a 2048-address /21 target
   admits unbounded distinct agent-chosen `finding_id`s, each fanning out through
   `discovery_service._emit_ws_event` to every connected client.

**Log hygiene (plan §7).** `hostname`, `banner` and `evidence` are untrusted
observations — a PTR answer from a resolver the agent does not control, whatever
bytes a service chose to send, and free text respectively. None of them appears
in a rejection reason, a log line or an `agent_events.detail`; a reason carries a
machine-readable code and at most the address, and even that goes through
`core.log_sanitize.safe_log_fragment` so it cannot forge a second log record.
The untrusted values still reach `scan_results` verbatim, because a review queue
that sanitizes its own evidence is not evidence.

Terminal-summary finalization is **Task 21's**. A `kind="summary"` frame takes
every check above and then stops: it writes no row and emits nothing, and
`SUMMARY_FINDING_ALLOWANCE` is the headroom the ceiling reserves for it.

Speed matters. This runs on the `/link` socket read loop, and that loop is what
advances `last_heartbeat_at` against the server's 60 s dead-link deadline — so
the accepted path is a handful of indexed lookups, one insert and one commit.
"""

from __future__ import annotations

import ipaddress
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import agent_scope
from app.core.log_sanitize import safe_log_fragment
from app.core.time import utcnow, utcnow_iso
from app.db.models import Agent, ScanJob
from app.schemas.agent_frame import (
    DISCOVERY_KIND_SUMMARY,
    DISCOVERY_KINDS,
    DiscoveryFindingPayload,
)
from app.schemas.discovery import ScanResultOut
from app.services import (
    agent_registry,
    agent_telemetry,
    discovery_result_service,
    discovery_service,
)
from app.services.agent_capabilities import _LOCAL_DISCOVERY_BOUNDS

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

# What `ingest_discovery_finding` did, for the caller and for the tests. Not an
# audit vocabulary — `scan_results` and `agent_events` are that.
DISPOSITION_ACCEPTED = "accepted"
DISPOSITION_DUPLICATE = "duplicate"
DISPOSITION_SUMMARY = "summary"

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


class InvalidDiscoveryFinding(ValueError):
    """One rejected `discovery.finding`, carrying the audit trail it belongs in.

    The `agent_link` handler (Task 17) catches this, rate-limits it through
    `agent_telemetry.recordable_violation`, and records `event_type` — so a
    forged dispatch token is auditable as an authorization failure while a
    malformed body stays an ordinary protocol violation.

    `audited` is True when this module already wrote the event itself. Exactly
    one branch does: the finding-ceiling breach, which also closes the job and
    therefore has to commit its audit atomically with that write rather than
    hand it back to a caller that commits afterwards. The handler must skip its
    own `record_event` when this is set, or the breach records twice.
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
) -> InvalidDiscoveryFinding:
    reason = _reason(code, address)
    _logger.warning("agent %s discovery finding rejected: %s", agent_id, reason)
    return InvalidDiscoveryFinding(reason, event_type=event_type)


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
    _assert_dispatch_open(agent, job, received_at)

    if finding.kind == DISCOVERY_KIND_SUMMARY:
        # Everything a summary shares with a host finding has now run. The
        # terminal write — status, timestamps, `job_update` — is Task 21's, and
        # is deliberately not half-done here.
        return DISPOSITION_SUMMARY

    address = _authorized_address(db, agent, job, finding)
    return await _record_host_finding(db, agent, job, finding, address)


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


def _assert_dispatch_open(agent: Agent, job: ScanJob, received_at: datetime | None) -> None:
    if job.dispatch_status not in _OPEN_DISPATCH_STATUSES or job.status not in _OPEN_JOB_STATUSES:
        raise _reject(agent.id, REASON_DISPATCH_CLOSED, job.dispatch_status or job.status)

    now = _aware(received_at) if received_at is not None else utcnow()
    deadline = job.dispatch_deadline_at
    if deadline is not None and now > _aware(deadline) + LATE_FINDING_GRACE:
        raise _reject(agent.id, REASON_LATE_FINDING)


def _authorized_address(
    db: Session, agent: Agent, job: ScanJob, finding: DiscoveryFindingPayload
) -> str:
    """The finding's address, proven to be inside both the job's targets and its scope."""
    if not finding.ip_address:
        # `scan_results.ip_address` is NOT NULL, so an addressless host finding
        # would otherwise be an IntegrityError inside the `/link` read loop.
        raise _reject(agent.id, REASON_MISSING_ADDRESS)
    address = discovery_result_service.normalize_ip(finding.ip_address) or finding.ip_address

    if not _in_job_targets(job, address):
        raise _reject(
            agent.id, REASON_OUT_OF_TARGET, address, event_type=EVENT_CAPABILITY_VIOLATION
        )

    scope = derive_discovery_scope(db, agent.id)
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
) -> str:
    """Insert, count, commit, publish — in that order, and only all four together.

    The insert runs inside a SAVEPOINT because `uq_scan_results_job_finding` is
    the idempotency key and a pre-check is not one: two spool replays racing on
    separate connections both pass a `SELECT`. The ceiling is a compare-and-set
    on the same statement that increments the counters, for the same reason.
    """
    ceiling = max_findings_per_dispatch(discovery_grant_config(db, agent.id))
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
        _close_over_ceiling(db, agent, job, ceiling)
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


def _close_over_ceiling(db: Session, agent: Agent, job: ScanJob, ceiling: int) -> None:
    """Close the job and audit the breach, atomically.

    D-4's `agent_execution_error`: an agent producing more findings than its own
    address budget allows is not executing the job it was given. Task 21's
    `finalize_agent_job` owns the ordinary terminal path and its events; this one
    writes the columns directly because it must land in the same transaction as
    the `capability_violation` that explains it — which is also why the exception
    raised afterwards is marked `audited`.
    """
    job.status = "failed"
    job.dispatch_status = "execution_error"
    job.error_reason = ERROR_AGENT_EXECUTION_ERROR
    job.error_text = _reason(REASON_FINDING_CEILING, str(ceiling))
    job.completed_at = utcnow_iso()
    record, count = agent_telemetry.recordable_violation(agent.id)
    if record:
        agent_registry.record_event(
            db,
            agent.id,
            EVENT_CAPABILITY_VIOLATION,
            detail={"reason": job.error_text, "scan_job_id": job.id, "repeated": count},
        )
    db.commit()


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
    "DISPOSITION_ACCEPTED",
    "DISPOSITION_DUPLICATE",
    "DISPOSITION_SUMMARY",
    "ERROR_AGENT_DISCONNECTED",
    "ERROR_AGENT_EXECUTION_ERROR",
    "ERROR_AGENT_REJECTED",
    "ERROR_AGENT_UNAVAILABLE",
    "ERROR_CAPABILITY_DISABLED",
    "ERROR_DISPATCH_FAILED",
    "ERROR_PROFILE_DISABLED",
    "ERROR_SCOPE_CHANGED",
    "JOB_ERROR_REASONS",
    "LATE_FINDING_GRACE",
    "MAX_FINDINGS_PER_DISPATCH",
    "MAX_FINDING_BYTES",
    "SUMMARY_FINDING_ALLOWANCE",
    "InvalidDiscoveryFinding",
    "discovery_grant_config",
    "ingest_discovery_finding",
    "max_findings_per_dispatch",
    "validate_finding_payload",
]
