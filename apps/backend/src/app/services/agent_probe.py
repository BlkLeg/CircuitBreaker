"""`probe.result` ingest — the one surface a remote agent can move monitor state from (§4).

Everything else an agent sends is additive telemetry: a bad host sample makes a
graph wrong. A bad probe result makes a monitor go DOWN, fires an alert, and
rewrites uptime. So the acceptance rules in §4 are enforced here as security
invariants, in a fixed order, and each one is pinned by a named test in
`tests/services/test_agent_probe_ingest.py`:

1. **Size, before anything parses.** Nothing upstream bounds an inbound frame —
   `ws_agents.link_stream` reads the socket without a limit and
   `agent_link.receive_frame` only parses JSON — so this handler is the cap.
   `details` above 64 KiB and any message above 2,000 characters are dealt with
   before the payload is validated, let alone matched against a run.
2. **Authentication, as a triple.** The `run_id`, the monitor it names, and the
   authenticated agent must all agree. `run_id` is a server-minted opaque
   128-bit token and is the only identifier that ever reaches the agent, so a
   guessed or leaked `monitor_id` buys nothing. A mismatch is recorded as a
   `capability_violation` — it is what a stolen token looks like, not a schema
   mistake.
3. **The deadline, against server receipt time.** `probe.result` is a data frame
   and therefore spools across an outage; a spooled frame keeps its original
   producer `TS` (the Go agent stamps `TS` only when it is zero). `frame.ts` is
   agent-clock provenance and is never arrival time, so the lease is judged
   against the server's own clock. Past `deadline_at + 30s` the run records what
   arrived and the monitor does not.
4. **Idempotency.** A run that is no longer open is inert — no second sample, no
   second transition, no second event.

Every outcome that touches the monitor reaches the shared result service
(`services/monitoring/result_service.py`, Global Constraints' one result path) —
`completed` on its state-machine branch, `execution_error` and `rejected` on its
execution branch. The latter two say nothing about the target and deliberately
never write an `avail` sample or touch the retry counter (§6, D-12) even when the
payload claims to carry one, but they are not silent either: the service is what
closes the run, records §6's one-event-per-change-of-reason `execution` event,
and publishes D-13's live refresh (which carries no `status` key). Recording the
condition inline here instead would leave the monitor's history empty for the
whole outage and push nothing.

`cancelled` is the exception, and only because it is not an execution condition
at all: the server asked for the stop (§4, Task 14), so the lease closes as audit
and the monitor is left entirely alone.

Secrets travel outbound only (D-10). §4 forbids credentials, authorization
headers and response bodies coming back, the agent is built not to echo them,
and this module does not take its word for it: the monitor's own secret config
values, plus anything under a secret-shaped key, are redacted out of `details`
and `msg` before either is persisted to `monitor_probe_runs.result_metadata`.

Speed matters. This runs on the `/link` socket read loop, and that loop is what
advances `last_heartbeat_at` against the server's 60 s dead-link deadline — so
the path is two indexed lookups and one commit, with no network call before the
result is durable.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Agent, MonitorItem, MonitorProbeRun
from app.schemas.agent_frame import ProbeResultPayload
from app.services.monitoring import result_service
from app.services.monitoring.collectors import Sample

_logger = logging.getLogger(__name__)

# §4's stated limits. Both are enforced on the raw payload before validation.
MAX_DETAILS_BYTES = 64 << 10
MAX_MSG_CHARS = 2000
# §4 also requires samples to satisfy a size limit and names no number. The
# widest collector in the parity contract is ICMP with six samples, so this is
# two orders of magnitude of headroom over any legitimate result and still a
# bound — an unbounded list is the one part of the payload the 64 KiB `details`
# cap does not already cover.
MAX_SAMPLES = 64
# §4: "It arrives before `deadline_at + 30 seconds`."
LATE_RESULT_GRACE = timedelta(seconds=30)

OUTCOME_COMPLETED = "completed"
OUTCOME_EXECUTION_ERROR = "execution_error"
OUTCOME_CANCELLED = "cancelled"
OUTCOME_REJECTED = "rejected"
# The closed vocabulary from §4. Anything else is a protocol violation rather
# than a silently-ignored result, because "unknown outcome" must never be
# mistaken for "the target is fine".
OUTCOMES = frozenset(
    {OUTCOME_COMPLETED, OUTCOME_EXECUTION_ERROR, OUTCOME_CANCELLED, OUTCOME_REJECTED}
)

# The two `monitor_probe_runs.status` values that still accept a result; they are
# also the two the partial unique index covers, so leaving one open wedges the
# monitor until the reconciliation pass expires it.
_OPEN_STATUSES = frozenset({"queued", "dispatched"})

# What `ingest_probe_result` did, for the caller and for the tests. Not an audit
# vocabulary — the run row is that.
DISPOSITION_ACCEPTED = "accepted"
DISPOSITION_AUDIT_ONLY = "audit_only"
DISPOSITION_LATE = "late"
DISPOSITION_DUPLICATE = "duplicate"

# `monitor_probe_runs.error_code` / `monitor_items.probe_execution_reason`, in
# the same machine-readable style `probe_eligibility` uses for its denials.
ERROR_LATE_RESULT = "late_result"
REASON_AGENT_EXECUTION_ERROR = "agent_execution_error"
REASON_AGENT_REJECTED = "agent_rejected"
REASON_AGENT_CANCELLED = "agent_cancelled"

_ERROR_FOR_OUTCOME = {
    OUTCOME_EXECUTION_ERROR: REASON_AGENT_EXECUTION_ERROR,
    OUTCOME_REJECTED: REASON_AGENT_REJECTED,
    OUTCOME_CANCELLED: REASON_AGENT_CANCELLED,
}
# The outcomes that mean "the vantage could not answer". Both are execution
# conditions and both go through the shared result service's execution branch,
# which is what writes the run, the `monitor_events` row and the live refresh.
_EXECUTION_CONDITION_OUTCOMES = frozenset({OUTCOME_EXECUTION_ERROR, OUTCOME_REJECTED})
# A cancellation is something the server asked for (§4, Task 14), so it closes
# the run without claiming the vantage is broken.
RUN_STATUS_CANCELLED = "cancelled"

# The audit trail a rejection lands in. `capability_violation` is reserved for
# the cases where the agent reached for something that is not its to touch —
# the same distinction `agent_link.dispatch_frame` already draws for an
# ungranted frame type.
EVENT_PROTOCOL_VIOLATION = "protocol_violation"
EVENT_CAPABILITY_VIOLATION = "capability_violation"

# Redaction. Key-shaped matching catches an echoed credential wherever it sits
# in `details`; value-shaped matching catches one that was pasted into free text
# under an innocent key.
_SECRET_KEY_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "credential",
    "cookie",
    "api_key",
    "apikey",
    "private_key",
    "bearer",
)
_SECRET_CONFIG_KEYS = frozenset({"password", "token", "secret", "api_key", "apikey"})
_SECRET_HEADER_KEYS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "x-api-key", "x-auth-token"}
)
# Short strings are not credentials worth matching on and would redact ordinary
# words out of every message ("GET", "up").
_MIN_REDACTABLE_SECRET = 6
REDACTED = "[redacted]"


class InvalidProbeResult(ValueError):
    """One rejected `probe.result`, carrying the audit trail it belongs in.

    `agent_link._handle_probe_result` catches this, rate-limits it through
    `agent_telemetry.recordable_violation`, and records `event_type` — so a
    forged run token is auditable as an authorization failure while a malformed
    body stays an ordinary protocol violation.
    """

    def __init__(self, message: str, *, event_type: str = EVENT_PROTOCOL_VIOLATION) -> None:
        super().__init__(message)
        self.event_type = event_type


def validate_probe_payload(payload: dict[str, Any]) -> ProbeResultPayload:
    """Size limits, then schema, then the outcome vocabulary — in that order.

    The size checks run against the raw mapping rather than the parsed model on
    purpose: parsing a hostile 40 MiB `details` blob to find out it is too big
    is the cost this is meant to avoid.
    """
    if not isinstance(payload, dict):
        raise InvalidProbeResult("payload is not an object")

    details = payload.get("details")
    if details is not None:
        try:
            encoded = json.dumps(details, separators=(",", ":"), default=str).encode()
        except (TypeError, ValueError) as exc:
            raise InvalidProbeResult("details is not serializable") from exc
        if len(encoded) > MAX_DETAILS_BYTES:
            raise InvalidProbeResult(f"details exceeds {MAX_DETAILS_BYTES} bytes")

    samples = payload.get("samples")
    if isinstance(samples, list) and len(samples) > MAX_SAMPLES:
        raise InvalidProbeResult(f"samples exceeds {MAX_SAMPLES} entries")

    msg = payload.get("msg")
    if isinstance(msg, str) and len(msg) > MAX_MSG_CHARS:
        # Truncated, not rejected: an over-long message is a chatty checker, not
        # an attack, and discarding the whole result would lose a real target
        # transition over cosmetics.
        payload = {**payload, "msg": msg[:MAX_MSG_CHARS]}

    try:
        result = ProbeResultPayload.model_validate(payload)
    except ValidationError as exc:
        raise InvalidProbeResult("payload schema is invalid") from exc

    if result.outcome not in OUTCOMES:
        raise InvalidProbeResult(f"unsupported outcome {result.outcome!r}")
    return result


async def ingest_probe_result(
    db: Session,
    agent: Agent,
    payload: dict[str, Any],
    *,
    received_at: datetime | None = None,
) -> str:
    """Accept, audit, or refuse one `probe.result`. Returns the disposition.

    `received_at` exists so tests can pin the deadline rule; production callers
    omit it and get the server's own clock, which is the whole point — see the
    module docstring on why `frame.ts` must never be used here.

    Owns its commit on every branch that writes, so a rejected frame leaves the
    session exactly as it found it and the caller's `record_event` is the only
    thing left to persist.
    """
    if agent.status != "active":
        raise InvalidProbeResult("agent is not active")

    result = validate_probe_payload(payload)

    run = db.execute(
        select(MonitorProbeRun).where(MonitorProbeRun.run_id == result.run_id)
    ).scalar_one_or_none()
    if run is None:
        raise InvalidProbeResult(
            f"unknown run {result.run_id!r}", event_type=EVENT_CAPABILITY_VIOLATION
        )
    if run.agent_id != agent.id:
        raise InvalidProbeResult(
            "run belongs to another agent", event_type=EVENT_CAPABILITY_VIOLATION
        )
    if run.monitor_id != result.monitor_id:
        raise InvalidProbeResult(
            "run does not belong to that monitor", event_type=EVENT_CAPABILITY_VIOLATION
        )

    monitor = db.get(MonitorItem, run.monitor_id)
    if monitor is None:  # pragma: no cover - the FK CASCADE removes the run with it
        raise InvalidProbeResult("monitor no longer exists")

    if run.status not in _OPEN_STATUSES:
        # Already completed, expired or cancelled. Inert by design: a retried or
        # duplicated spool entry must not write a second sample or replay a
        # transition that already fired.
        _logger.debug("probe result for %s run %s ignored", run.status, run.run_id)
        return DISPOSITION_DUPLICATE

    secrets = _secret_values(monitor.params)
    msg = _redact_text(result.msg, secrets)
    details = _scrub(result.details, secrets) if result.details is not None else None

    # Recorded on every accepted branch, late included: when the check actually
    # began is audit the run row owes an operator regardless of whether the
    # result was still allowed to move monitor state.
    run.started_at = _aware(result.started_at)

    now = _aware(received_at) if received_at is not None else utcnow()
    if run.deadline_at is not None and now > _aware(run.deadline_at) + LATE_RESULT_GRACE:
        _close_run(
            run,
            result,
            status="expired",
            error_code=ERROR_LATE_RESULT,
            msg=msg,
            details=details,
            completed_at=now,
        )
        db.commit()
        return DISPOSITION_LATE

    if result.outcome == OUTCOME_CANCELLED:
        # The one outcome that is neither a target result nor an execution
        # condition: the server asked for the stop, so the lease closes and
        # nothing about the monitor changes — no condition, no event, no push.
        _close_run(
            run,
            result,
            status=RUN_STATUS_CANCELLED,
            error_code=REASON_AGENT_CANCELLED,
            msg=msg,
            details=details,
            completed_at=_aware(result.finished_at),
        )
        db.commit()
        return DISPOSITION_AUDIT_ONLY

    record = result_service.MonitorResult(
        item_id=monitor.id,
        target_type=monitor.target_type,
        target_id=monitor.target_id,
        check_type=monitor.check_type,
        samples=[Sample(s.metric, float(s.value), s.error_reason) for s in result.samples],
        up=result.up,
        msg=msg,
        # The agent's own finish time, not arrival: the samples describe when the
        # check ran, and a spooled result must not land in the timeseries at the
        # moment the link happened to come back.
        checked_at=_aware(result.finished_at),
        # Carried through verbatim so the run keeps the agent's own word for
        # audit; the service switches on "is this `completed`", so `rejected`
        # takes the same inert branch `execution_error` does.
        outcome=result.outcome,
        details=details,
        source=result_service.SOURCE_AGENT,
        agent_id=agent.id,
        run_id=run.run_id,
        execution_reason=_ERROR_FOR_OUTCOME.get(result.outcome),
    )
    # Both branches go through the one result path (Global Constraints).
    # `execution_error`/`rejected` are inert with respect to the target — no
    # avail sample, no retry increment, no transition, and `probe_last_result_at`
    # deliberately untouched so D-4's staleness rule still sees a monitor that is
    # producing no real results — but they are *not* invisible: the service is
    # where the run closes, where §6's "one execution event per change of reason"
    # is enforced, and where D-13's status-less live refresh is published.
    # Writing the probe columns here instead would leave the monitor's history
    # empty for the whole outage and push nothing to `monitor:{id}`.
    persisted = result_service.persist_results(db, [record])
    await result_service.publish_results(persisted)
    if result.outcome in _EXECUTION_CONDITION_OUTCOMES:
        return DISPOSITION_AUDIT_ONLY
    return DISPOSITION_ACCEPTED


def _close_run(
    run: MonitorProbeRun,
    result: ProbeResultPayload,
    *,
    status: str,
    error_code: str,
    msg: str,
    details: dict | None,
    completed_at: datetime,
) -> None:
    """Record what arrived without letting it reach monitor state.

    `outcome` stays whatever the agent reported — it is the audit answer to "what
    did the executor say" — while `status` records where the run actually got to,
    which for a late result is `expired`, not `completed`.
    """
    run.status = status
    run.outcome = result.outcome
    run.error_code = error_code
    run.completed_at = completed_at
    run.msg = msg[:MAX_MSG_CHARS] or None
    run.result_metadata = {"details": details} if details else None


def _aware(value: datetime) -> datetime:
    """`ProbeResultPayload` and `monitor_probe_runs` both admit naive datetimes;
    comparing one against the other would raise inside the /link read loop and
    take the connection down over a cosmetic serialization difference."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _secret_values(params: Any) -> tuple[str, ...]:
    """The monitor's own credentials, as literal strings to look for.

    Derived from the stored configuration rather than from a list of key names
    the agent chose, so an echoed password is caught even when it comes back
    under a harmless-looking key.
    """
    if not isinstance(params, dict):
        return ()
    found: list[str] = []
    for key, value in params.items():
        if str(key).lower() in _SECRET_CONFIG_KEYS and isinstance(value, str):
            found.append(value)
    headers = params.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() in _SECRET_HEADER_KEYS and isinstance(value, str):
                found.append(value)
                # "Bearer <token>": the credential alone is what would be echoed
                # back by a checker that logged the token rather than the header.
                parts = value.split()
                if len(parts) == 2:
                    found.append(parts[1])
    unique = {s for s in found if len(s) >= _MIN_REDACTABLE_SECRET}
    # Longest first: redacting "Bearer <token>" before "<token>" keeps the
    # replacement from leaving a recognizable fragment behind.
    return tuple(sorted(unique, key=len, reverse=True))


def _is_secret_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def _scrub(value: Any, secrets: Iterable[str]) -> Any:
    """Drop secret-shaped keys and redact known secret values, recursively."""
    if isinstance(value, dict):
        return {k: _scrub(v, secrets) for k, v in value.items() if not _is_secret_key(k)}
    if isinstance(value, list):
        return [_scrub(v, secrets) for v in value]
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _redact_text(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text


__all__ = [
    "DISPOSITION_ACCEPTED",
    "DISPOSITION_AUDIT_ONLY",
    "DISPOSITION_DUPLICATE",
    "DISPOSITION_LATE",
    "MAX_DETAILS_BYTES",
    "MAX_MSG_CHARS",
    "MAX_SAMPLES",
    "InvalidProbeResult",
    "ingest_probe_result",
    "validate_probe_payload",
]
