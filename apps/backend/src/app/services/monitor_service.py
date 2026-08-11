"""Monitor service: monitor-id CRUD, events, history, and per-target rollups."""

import asyncio
import json
import logging
import re
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.nats_client import nats_client
from app.core.subjects import MONITOR_POLL_ITEM, MONITOR_PROBE_REMOTE
from app.db.models import (
    Agent,
    ComputeUnit,
    ExternalNode,
    Hardware,
    MonitorDailyStats,
    MonitorEvent,
    MonitorItem,
    MonitorProbeRun,
    Service,
    TelemetryTimeseries,
)
from app.schemas.agent_frame import TYPE_PROBE_CANCEL
from app.schemas.monitor import CONFIG_MODELS, MonitorCreate, MonitorUpdate
from app.services.monitoring import result_service
from app.services.monitoring.state import PENDING

logger = logging.getLogger(__name__)


# ── Remote-probe cancellation (Slice 3 §4, §8) ────────────────────────────────
# Five events retire an in-flight run: a monitor is paused, deleted or
# reassigned, an agent's `remote_probe` grant is turned off, or the agent is
# revoked. All five go through the two functions below, and all five close the
# run in the database *before* trying to tell the agent — §4 makes the frame
# best-effort and the backend authoritative, so a result for a closed run is
# refused on arrival whether or not the cancel was ever delivered.
#
# Closing the run is not tidiness. `uq_monitor_probe_runs_active` is a partial
# unique index over `(monitor_id) WHERE status IN ('queued','dispatched')`, so a
# run left in flight blocks every future run for that monitor until the
# reconciliation pass expires it.

# `monitor_probe_runs.error_code` / the `probe.cancel` frame's advisory
# `reason`, in the same machine-readable style `probe_eligibility` uses for its
# denials. The two agent-wide reasons double as
# `monitor_items.probe_execution_reason`, which is why they read as conditions
# ("the grant is off", "the agent is revoked") rather than as verbs.
CANCEL_MONITOR_PAUSED = "monitor_paused"
CANCEL_MONITOR_DELETED = "monitor_deleted"
CANCEL_MONITOR_REASSIGNED = "monitor_reassigned"
CANCEL_CAPABILITY_DISABLED = "capability_disabled"
CANCEL_AGENT_REVOKED = "agent_revoked"

# The two statuses the partial unique index covers.
_ACTIVE_RUN_STATUSES = ("queued", "dispatched")


class ProbeCancel(NamedTuple):
    """One retired run, addressed to the agent that still thinks it owns it."""

    agent_id: int
    run_id: str
    reason: str


@dataclass(frozen=True)
class ProbeCancellation:
    """What a trigger owes the outside world once its transaction commits.

    Deliberately inert on its own: a trigger builds one, commits, and only then
    hands it to `publish_probe_cancels` / `schedule_probe_cancels`. Nothing is
    published from inside the transaction, for the same reason
    `result_service.persist_results` publishes nothing — an agent must never be
    told to abandon a run that a rollback then reinstates.
    """

    cancels: list[ProbeCancel] = field(default_factory=list)
    live_status: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.cancels or self.live_status)


def _publish_soon(what: str, factory: Callable[[], Coroutine[Any, Any, Any]]) -> bool:
    """Fire-and-forget an async publish from a synchronous caller.

    The single home of the `asyncio.get_running_loop()` + `create_task` idiom,
    so every cancellation trigger behaves identically. Takes a factory rather
    than a coroutine so nothing is ever constructed and then abandoned
    unawaited.

    Returns False, having published nothing, when no loop is running — which is
    the case for every `def` route FastAPI hands to its threadpool. That is what
    "best-effort" means concretely in §4: the run is already closed in the
    database by the time this is called, so an undelivered `probe.cancel` costs
    the agent one wasted check and costs the backend nothing at all.

    **Cancellation only.** Anything that *opens* a run must await its publish
    instead (`_dispatch_probe_run`): there the run is live and unannounced until
    the frame lands, so silently publishing nothing wedges the monitor rather
    than costing it a wasted check.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running async loop to publish %s.", what)
        return False
    loop.create_task(factory())
    return True


def _close_active_runs(
    db: Session,
    reason: str,
    *,
    monitor_ids: Sequence[int] | None = None,
    agent_id: int | None = None,
) -> list[ProbeCancel]:
    """Retire the matching in-flight runs. Caller owns the transaction.

    `outcome` is left NULL on purpose: it records what the *agent* reported, and
    on this path the agent reported nothing — the server took the run away.
    `error_code` is what distinguishes a cancellation from an expiry.
    """
    stmt = select(MonitorProbeRun).where(MonitorProbeRun.status.in_(_ACTIVE_RUN_STATUSES))
    if monitor_ids is not None:
        if not monitor_ids:
            return []
        stmt = stmt.where(MonitorProbeRun.monitor_id.in_(monitor_ids))
    if agent_id is not None:
        stmt = stmt.where(MonitorProbeRun.agent_id == agent_id)
    now = datetime.now(UTC)
    cancels: list[ProbeCancel] = []
    for run in db.scalars(stmt):
        run.status = "cancelled"
        run.error_code = reason[:64]
        run.completed_at = now
        cancels.append(ProbeCancel(run.agent_id, run.run_id, reason))
    return cancels


def cancel_monitor_probe_runs(
    db: Session, monitor_ids: int | Sequence[int], *, reason: str
) -> ProbeCancellation:
    """Retire whatever runs these monitors have in flight.

    Takes a sequence as well as a single id so a bulk trigger
    (`set_target_paused`) closes its runs in one statement instead of one per
    monitor. Caller owns the transaction.

    No execution condition is recorded: pausing, deleting or reassigning a
    monitor says nothing about whether its vantage works, and `stale`/
    `unavailable` are answers to that question alone.
    """
    ids = [monitor_ids] if isinstance(monitor_ids, int) else list(monitor_ids)
    return ProbeCancellation(cancels=_close_active_runs(db, reason, monitor_ids=ids))


def cancel_agent_probe_runs(db: Session, agent_id: int, *, reason: str) -> ProbeCancellation:
    """Retire every run an agent holds and mark its assignments unavailable.

    §8 is explicit that the assignments are *preserved*: a revoked or ungranted
    agent's monitors become unavailable, they do not quietly fall back to server
    execution. Re-approving the agent therefore restores the vantage instead of
    requiring every monitor to be reassigned by hand.

    Caller owns the transaction.
    """
    cancels = _close_active_runs(db, reason, agent_id=agent_id)
    now = datetime.now(UTC)
    live: list[dict] = []
    for monitor_id in db.scalars(
        select(MonitorItem.id)
        .where(MonitorItem.probe_agent_id == agent_id)
        .order_by(MonitorItem.id)
    ):
        entry = result_service.record_execution_condition(
            db,
            monitor_id,
            status=result_service.EXECUTION_UNAVAILABLE,
            reason=reason,
            occurred_at=now,
        )
        if entry is not None:
            live.append(entry)
    return ProbeCancellation(cancels=cancels, live_status=live)


async def publish_probe_cancels(cancellation: ProbeCancellation) -> int:
    """Tell the agents, and refresh the cards. Returns the frames published.

    Never raises: `publish_agent_control_frame` already swallows a dead Redis,
    and a monitor whose run is closed must not be undone by a delivery failure.
    """
    from app.services import agent_registry

    delivered = 0
    for cancel in cancellation.cancels:
        published = await agent_registry.publish_agent_control_frame(
            cancel.agent_id,
            {
                "type": TYPE_PROBE_CANCEL,
                "payload": {"run_id": cancel.run_id, "reason": cancel.reason},
            },
        )
        delivered += 1 if published else 0
    if cancellation.live_status:
        # D-13: these payloads carry no `status` key, so the card's UP/DOWN pill
        # keeps the last target state while the execution condition changes.
        await result_service.publish_results(
            result_service.PersistedResults(live_status=list(cancellation.live_status))
        )
    return delivered


def schedule_probe_cancels(cancellation: ProbeCancellation) -> bool:
    """The synchronous callers' half of `publish_probe_cancels`."""
    if not cancellation:
        return False
    return _publish_soon("probe cancellations", lambda: publish_probe_cancels(cancellation))


# ── Assignment validation (§7, D-9) ───────────────────────────────────────────


class InvalidAssignment(ValueError):
    """A vantage the monitor may not be given. `api/monitor.py` turns it into a
    422, alongside the config `ValidationError` the same routes already map."""


def validate_probe_assignment(
    db: Session,
    agent_id: int | None,
    target_type: str | None,
    target_id: int | None,
) -> None:
    """Refuse an assignment the server can already tell will never be legal.

    Two rules, both cheap and both synchronous, so the write path never has to
    reach for Redis or DNS:

    * the agent has to exist — `monitor_items.probe_agent_id` is a RESTRICT FK,
      so an unknown id would otherwise surface as an unhandled IntegrityError;
    * D-9's tenant rule: refuse only when *both* sides carry a tenant and they
      differ. A tenant-less standalone monitor stays legal on a tenant-scoped
      agent, because the target is still bounded by that agent's own derived
      scope.

    Everything else §2 requires — liveness, readiness, scope — is a *condition*
    rather than a permanent property, and is answered at dispatch and again on
    the agent. Refusing to save on a condition would make an assignment
    impossible to prepare while its agent happens to be offline.
    """
    if agent_id is None:
        return
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise InvalidAssignment(f"Unknown probe agent {agent_id}")
    if agent.tenant_id is None:
        return
    monitor_tenant = _target_tenant_id(db, target_type, target_id)
    if monitor_tenant is not None and monitor_tenant != agent.tenant_id:
        raise InvalidAssignment(
            f"Agent {agent_id} belongs to a different tenant than this monitor's target"
        )


def _target_tenant_id(db: Session, target_type: str | None, target_id: int | None) -> int | None:
    """The monitor's tenant, derived exactly as the dispatcher derives it.

    Routed through `probe_eligibility` rather than re-deriving it here: D-9 is
    application-only (`monitor_items` has no `tenant_id` and is not in
    `0040_rls_policies`), so a second table of per-target-type tenant lookups
    would be a second answer to the same question.
    """
    from app.services.monitoring import probe_eligibility

    probe = MonitorItem(target_type=target_type, target_id=target_id)
    return probe_eligibility._monitor_tenant_id(db, probe)


def reader_can_access_monitor(db: Session, reader: object, monitor: Mapping[str, Any]) -> bool:
    """Return whether ``reader`` may see a monitor row under the v1 tenant rule.

    v1 is single-tenant per deployment, but upgraded data can still carry legacy
    tenant ids. To avoid identifier enumeration in that transitional state, a
    read is hidden only when both the reader and target have tenant ids and they
    differ. Tenantless rows remain visible for single-tenant compatibility.
    """

    reader_tenant_id = getattr(reader, "tenant_id", None)
    if reader_tenant_id is None:
        return True
    target_tenant_id = _target_tenant_id(
        db,
        monitor.get("target_type"),
        monitor.get("target_id"),
    )
    return target_tenant_id is None or target_tenant_id == reader_tenant_id


def filter_readable_monitors(
    db: Session, reader: object, monitors: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    return [monitor for monitor in monitors if reader_can_access_monitor(db, reader, monitor)]


# ── Serialization (the single monitor dict every route returns) ───────────────


def _probe_agents(db: Session, items: Sequence[MonitorItem]) -> dict[int, dict]:
    """`{agent_id: {"id", "name"}}` for the vantages these monitors name.

    One bulk query for a whole list — `_to_dict` feeds the dashboard's overview,
    so resolving the agent per monitor would be an N+1 on the page the overview
    endpoint exists to collapse into four queries.
    """
    agent_ids = {item.probe_agent_id for item in items if item.probe_agent_id is not None}
    if not agent_ids:
        return {}
    rows = db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))).all()
    return {agent_id: {"id": agent_id, "name": name} for agent_id, name in rows}


def _probe_block(item: MonitorItem, probe_agents: dict[int, dict] | None = None) -> dict:
    """§7's probe block. `probe_mode` is derived, never stored: `probe_agent_id
    IS NULL` is server execution and there is no third vantage."""
    agent_id = item.probe_agent_id
    return {
        "probe_agent_id": agent_id,
        "probe_mode": "server" if agent_id is None else "agent",
        "probe_agent": (probe_agents or {}).get(agent_id) if agent_id is not None else None,
        "probe_execution_status": item.probe_execution_status,
        "probe_execution_reason": item.probe_execution_reason,
        "probe_last_dispatched_at": item.probe_last_dispatched_at,
        "probe_last_result_at": item.probe_last_result_at,
    }


def _to_dict(
    item: MonitorItem,
    uptime_pct_24h: float | None = None,
    latency_ms: float | None = None,
    probe_agents: dict[int, dict] | None = None,
) -> dict:
    return {
        **_probe_block(item, probe_agents),
        "id": item.id,
        "name": item.name,
        "check_type": item.check_type,
        "host": item.host,
        "config": item.params or {},
        "interval_secs": item.interval_secs,
        "max_retries": item.max_retries,
        "retry_interval_secs": item.retry_interval_secs,
        "enabled": item.enabled,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "status": item.last_status or PENDING,
        "retries": item.consecutive_failures,
        "last_polled_at": item.last_polled_at,
        "last_status_change_at": item.last_status_change_at,
        "uptime_pct_24h": uptime_pct_24h,
        "latency_ms": latency_ms,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _latest_metric_map(db: Session, item_ids: list[int], metric: str) -> dict[int, float]:
    if not item_ids:
        return {}
    rows = (
        db.query(TelemetryTimeseries)
        .filter(TelemetryTimeseries.item_id.in_(item_ids), TelemetryTimeseries.metric == metric)
        .distinct(TelemetryTimeseries.item_id)
        .order_by(TelemetryTimeseries.item_id, TelemetryTimeseries.ts.desc())
        .all()
    )
    return {r.item_id: r.value for r in rows if r.item_id is not None}


def _avail_agg(db: Session, item_ids: list[int], hours: int) -> dict[int, tuple[float | None, int]]:
    """Mean `avail` and how many samples that mean is made of, per monitor.

    The count is what makes the mean readable (D-12): an agent that could not
    run a check writes no `avail` sample at all (§2), so an unobserved stretch
    shrinks the denominator instead of showing as downtime and the average of
    the rows that happen to exist reads 100%.
    """
    if not item_ids:
        return {}
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = db.execute(
        select(
            TelemetryTimeseries.item_id,
            func.avg(TelemetryTimeseries.value),
            func.count(TelemetryTimeseries.value),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "avail",
            TelemetryTimeseries.ts >= since,
        )
        .group_by(TelemetryTimeseries.item_id)
    ).all()
    return {item_id: (avg, int(count)) for item_id, avg, count in rows}


def _uptime_pct_map(db: Session, item_ids: list[int], hours: int = 24) -> dict[int, float]:
    return {
        item_id: round(avg * 100, 1)
        for item_id, (avg, _count) in _avail_agg(db, item_ids, hours).items()
        if avg is not None
    }


def _window_coverage(sample_count: int, interval_secs: int, hours: int) -> dict:
    """Observed vs window minutes for one uptime window (D-12).

    Observation is counted in *scheduled checks*, not in minutes that happen to
    contain a sample: a landed check speaks for the interval it was scheduled
    on, so a 300s monitor with 288 samples observed the whole day. Counting
    minute buckets the way `workers/rollup_worker.py` does would call that same
    fully-observed day 20% covered and cry wolf on every monitor polling slower
    than once a minute. Retry polls run faster than the interval and can push
    the product past the window, hence the clamp.

    The denominator is the full window, never the monitor's age: shortening it
    would be the same silent denominator shrink this field exists to expose.
    """
    window_minutes = hours * 60
    interval_minutes = max(interval_secs, 1) / 60
    observed = min(window_minutes, round(sample_count * interval_minutes))
    return {
        "observed_minutes": observed,
        "window_minutes": window_minutes,
        "pct": round(observed / window_minutes * 100, 1),
    }


def _latency_series_map(db: Session, item_ids: list[int], limit: int) -> dict[int, list[float]]:
    """Last `limit` latency samples per monitor, oldest → newest (sparkline order)."""
    if not item_ids:
        return {}
    ranked = (
        select(
            TelemetryTimeseries.item_id,
            TelemetryTimeseries.value,
            TelemetryTimeseries.ts,
            func.row_number()
            .over(
                partition_by=TelemetryTimeseries.item_id,
                order_by=TelemetryTimeseries.ts.desc(),
            )
            .label("rn"),
        )
        .where(
            TelemetryTimeseries.item_id.in_(item_ids),
            TelemetryTimeseries.metric == "latency_ms",
        )
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.item_id, ranked.c.value)
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.ts.asc())
    ).all()
    series: dict[int, list[float]] = {}
    for item_id, value in rows:
        series.setdefault(item_id, []).append(value)
    return series


def _recent_checks_map(db: Session, item_ids: list[int], limit: int) -> dict[int, list[dict]]:
    """Last `limit` events per monitor, newest first — the shape CheckHistoryBar takes."""
    if not item_ids:
        return {}
    ranked = (
        select(
            MonitorEvent.id,
            MonitorEvent.item_id,
            MonitorEvent.status_to,
            MonitorEvent.msg,
            MonitorEvent.created_at,
            func.row_number()
            .over(partition_by=MonitorEvent.item_id, order_by=MonitorEvent.created_at.desc())
            .label("rn"),
        )
        .where(MonitorEvent.item_id.in_(item_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            ranked.c.id,
            ranked.c.item_id,
            ranked.c.status_to,
            ranked.c.msg,
            ranked.c.created_at,
        )
        .where(ranked.c.rn <= limit)
        .order_by(ranked.c.item_id, ranked.c.created_at.desc())
    ).all()
    checks: dict[int, list[dict]] = {}
    for ev_id, item_id, status_to, msg, created_at in rows:
        checks.setdefault(item_id, []).append(
            {"id": ev_id, "status_to": status_to, "msg": msg, "created_at": created_at}
        )
    return checks


def list_monitors(
    db: Session,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    enabled: bool | None = None,
) -> list[dict]:
    query = select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)
    if target_type is not None:
        query = query.where(MonitorItem.target_type == target_type)
    if target_id is not None:
        query = query.where(MonitorItem.target_id == target_id)
    if enabled is not None:
        query = query.where(MonitorItem.enabled == enabled)
    items = list(db.scalars(query).all())
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    agents = _probe_agents(db, items)
    return [_to_dict(i, uptimes.get(i.id), latencies.get(i.id), agents) for i in items]


def list_overview(db: Session, *, latency_points: int = 12, check_points: int = 20) -> list[dict]:
    """Everything the monitors dashboard renders, in one round trip.

    Four bulk queries regardless of monitor count — the page it feeds used to
    fetch events per monitor.
    """
    items = list(db.scalars(select(MonitorItem).order_by(MonitorItem.name, MonitorItem.id)).all())
    if not items:
        return []
    ids = [i.id for i in items]
    uptimes = _uptime_pct_map(db, ids)
    latencies = _latest_metric_map(db, ids, "latency_ms")
    series = _latency_series_map(db, ids, latency_points)
    checks = _recent_checks_map(db, ids, check_points)
    agents = _probe_agents(db, items)
    return [
        {
            **_to_dict(item, uptimes.get(item.id), latencies.get(item.id), agents),
            "latency_series": series.get(item.id, []),
            "recent_checks": checks.get(item.id, []),
        }
        for item in items
    ]


def get_monitor(db: Session, monitor_id: int) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    uptimes = _uptime_pct_map(db, [item.id])
    latencies = _latest_metric_map(db, [item.id], "latency_ms")
    return _to_dict(item, uptimes.get(item.id), latencies.get(item.id), _probe_agents(db, [item]))


def create_monitor(db: Session, payload: MonitorCreate) -> dict:
    validate_probe_assignment(db, payload.probe_agent_id, payload.target_type, payload.target_id)
    item = MonitorItem(
        name=payload.name,
        check_type=payload.check_type,
        host=payload.host,
        params=payload.config,
        interval_secs=payload.interval_secs,
        max_retries=payload.max_retries,
        retry_interval_secs=payload.retry_interval_secs,
        enabled=payload.enabled,
        target_type=payload.target_type,
        target_id=payload.target_id,
        probe_agent_id=payload.probe_agent_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _to_dict(item, probe_agents=_probe_agents(db, [item]))


def update_monitor(db: Session, monitor_id: int, payload: MonitorUpdate) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    data = payload.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        from app.schemas.monitor import CONFIG_MODELS

        model = CONFIG_MODELS[item.check_type]
        data["config"] = model(**data["config"]).model_dump(exclude_unset=True)
        item.params = data.pop("config")
    cancellation = ProbeCancellation()
    if "probe_agent_id" in data and data["probe_agent_id"] != item.probe_agent_id:
        validate_probe_assignment(
            db,
            data["probe_agent_id"],
            data.get("target_type", item.target_type),
            data.get("target_id", item.target_id),
        )
        # §8: the old vantage may still be executing. Its run has to be retired
        # before the column moves, or whatever it eventually posts would arrive
        # against a monitor that is no longer its own.
        cancellation = cancel_monitor_probe_runs(db, item.id, reason=CANCEL_MONITOR_REASSIGNED)
        item.probe_agent_id = data["probe_agent_id"]
        # The previous vantage's execution condition says nothing about the new
        # one, and carrying it over would render a stale "unavailable" against
        # an agent that has not been asked for anything yet.
        item.probe_execution_status = None
        item.probe_execution_reason = None
    for field_name in (
        "name",
        "host",
        "interval_secs",
        "max_retries",
        "retry_interval_secs",
        "enabled",
        "target_type",
        "target_id",
    ):
        if field_name in data:
            setattr(item, field_name, data[field_name])
    db.commit()
    db.refresh(item)
    schedule_probe_cancels(cancellation)
    return _to_dict(item, probe_agents=_probe_agents(db, [item]))


def delete_monitor(db: Session, monitor_id: int) -> bool:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return False
    # Captured (and flushed) before the delete: `monitor_probe_runs.monitor_id`
    # is ON DELETE CASCADE, so once this commits there is no run row left to
    # name in a `probe.cancel` frame.
    cancellation = cancel_monitor_probe_runs(db, item.id, reason=CANCEL_MONITOR_DELETED)
    db.flush()
    db.delete(item)
    db.commit()
    schedule_probe_cancels(cancellation)
    return True


def set_paused(db: Session, monitor_id: int, paused: bool) -> dict | None:
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return None
    item.enabled = not paused
    if not paused:
        item.next_due_at = datetime.now(UTC)
    # Resuming cancels nothing: the monitor had no run in flight to take away.
    cancellation = (
        cancel_monitor_probe_runs(db, item.id, reason=CANCEL_MONITOR_PAUSED)
        if paused
        else ProbeCancellation()
    )
    db.add(
        MonitorEvent(
            item_id=item.id,
            event_type="paused" if paused else "resumed",
            status_from=item.last_status,
            status_to=item.last_status or PENDING,
            msg="paused by user" if paused else "resumed by user",
        )
    )
    db.commit()
    db.refresh(item)
    schedule_probe_cancels(cancellation)
    return _to_dict(item, probe_agents=_probe_agents(db, [item]))


def get_events(db: Session, monitor_id: int, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(MonitorEvent)
        .where(MonitorEvent.item_id == monitor_id)
        .order_by(MonitorEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": e.id,
            "monitor_id": e.item_id,
            "event_type": e.event_type,
            "status_from": e.status_from,
            "status_to": e.status_to,
            "msg": e.msg,
            "duration_secs": e.duration_secs,
            "created_at": e.created_at,
        }
        for e in rows
    ]


def get_probe_runs(db: Session, monitor_id: int, limit: int = 20) -> list[dict]:
    """§7's bounded probe-run history for one monitor, newest first.

    `created_at` then `id` because a run created inside the same transaction as
    another shares its timestamp, and the history table must still be stable.
    `result_metadata` is not returned: it is the audit record behind the check
    (D-8), not something the history table renders.
    """
    rows = db.scalars(
        select(MonitorProbeRun)
        .where(MonitorProbeRun.monitor_id == monitor_id)
        .order_by(MonitorProbeRun.created_at.desc(), MonitorProbeRun.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "run_id": r.run_id,
            "agent_id": r.agent_id,
            "status": r.status,
            "outcome": r.outcome,
            "msg": r.msg,
            "error_code": r.error_code,
            "scheduled_at": r.scheduled_at,
            "dispatched_at": r.dispatched_at,
            "deadline_at": r.deadline_at,
            "started_at": r.started_at,
            "completed_at": r.completed_at,
            "attempt_count": r.attempt_count,
            "created_at": r.created_at,
        }
        for r in rows
    ]


def get_history(
    db: Session, monitor_id: int, metric: str = "latency_ms", hours: int = 24
) -> list[dict]:
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = (
        db.query(TelemetryTimeseries)
        .filter(
            TelemetryTimeseries.item_id == monitor_id,
            TelemetryTimeseries.metric == metric,
            TelemetryTimeseries.ts >= since,
        )
        .order_by(TelemetryTimeseries.ts.asc())
        .all()
    )
    return [{"ts": r.ts, "value": r.value} for r in rows]


def _rollup_pct(db: Session, item_id: int, *, since_date: str | None = None) -> float | None:
    query = select(
        func.sum(MonitorDailyStats.uptime_minutes), func.sum(MonitorDailyStats.total_minutes)
    ).where(MonitorDailyStats.item_id == item_id)
    if since_date is not None:
        query = query.where(MonitorDailyStats.date >= since_date)
    up, total = db.execute(query).one()
    if not total:
        return None
    return round(float(up) / float(total) * 100, 1)


def get_uptime(db: Session, monitor_id: int) -> dict:
    """Availability per window, each short window qualified by its coverage.

    `pct_*` alone cannot be read honestly: the short windows average the `avail`
    rows that exist, and a vantage that was unavailable wrote none (D-12). Every
    telemetry-backed window therefore ships `coverage_*` beside it. The
    rollup-backed windows (365d, total) do not, because `MonitorDailyStats`
    keeps no row for a wholly unobserved day and "all time" has no fixed
    denominator to compare against.
    """
    item = db.get(MonitorItem, monitor_id)
    since_365d = (datetime.now(UTC) - timedelta(days=365)).strftime("%Y-%m-%d")
    agg = {
        hours: _avail_agg(db, [monitor_id], hours).get(monitor_id, (None, 0))
        for hours in (24, 24 * 7, 24 * 30)
    }

    def _pct(hours: int) -> float | None:
        avg, _count = agg[hours]
        return None if avg is None else round(avg * 100, 1)

    def _coverage(hours: int) -> dict | None:
        if item is None:
            return None
        return _window_coverage(agg[hours][1], item.interval_secs, hours)

    return {
        "pct_24h": _pct(24),
        "pct_7d": _pct(24 * 7),
        "pct_30d": _pct(24 * 30),
        "pct_365d": _rollup_pct(db, monitor_id, since_date=since_365d),
        "pct_total": _rollup_pct(db, monitor_id),
        "last_polled_at": item.last_polled_at if item else None,
        "coverage_24h": _coverage(24),
        "coverage_7d": _coverage(24 * 7),
        "coverage_30d": _coverage(24 * 30),
    }


@dataclass(frozen=True)
class CheckDispatch:
    """Whether "check now" was accepted, and if not, why (D-14).

    `found` separates "no such monitor" (404) from "this vantage cannot take the
    check right now" (409): §2 forbids falling back to the server, so a refusal
    is the only honest answer and it has to carry `probe_eligibility`'s
    machine-readable reason rather than a 200 the operator would read as
    "queued".
    """

    ok: bool
    reason: str | None = None
    found: bool = True


async def _dispatch_probe_run(db: Session, item: MonitorItem, run_id: str) -> str | None:
    """Announce a freshly opened run to the dispatch worker, or close it again.

    Awaited, never handed to `_publish_soon`: that helper is best-effort because
    the run it announces is *already closed*, so a lost frame costs nothing.
    Here the run is freshly **open** and this publish is the only thing that
    makes it live. A run left `queued` holds `uq_monitor_probe_runs_active`, so
    the next tick that finds the monitor due takes D-6's `previous_run_in_flight`
    skip and the D-5 reconciliation pass then writes a spurious `result_timeout`
    — an operator's successful button press turning into a lost interval and a
    false "vantage timed out".

    A publish that fails therefore closes the run exactly as
    `monitor_probe_dispatch` closes one it cannot deliver — same status, same
    `dispatch_failed` code, same execution condition on the monitor — with one
    difference: `next_due_at` is left alone. The scheduler pulls it back because
    it had already advanced it when it claimed the item; a manual check never
    touched the schedule and must not start now.

    Returns None when the assignment is on its way, or the `error_code` written
    to the run — which doubles as the availability reason "check now" answers
    409 with.
    """
    if await nats_client.js_publish(MONITOR_PROBE_REMOTE, {"run_id": run_id}):
        return None
    # Reaching into the dispatch worker on purpose: it owns the single
    # definition of "the assignment could not be delivered" (§8), and a second
    # copy here would be free to drift from it.
    from app.workers import monitor_probe_dispatch

    reason = monitor_probe_dispatch._DISPATCH_FAILED
    logger.warning("Failed to dispatch probe run %s for monitor %s", run_id, item.id)
    run = db.scalars(select(MonitorProbeRun).where(MonitorProbeRun.run_id == run_id)).first()
    if run is not None:
        monitor_probe_dispatch._close_unavailable(db, run, item, reason)
    return reason


def _poll_payload(item: MonitorItem) -> dict:
    return {
        "item_id": item.id,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "host": item.host,
        "check_type": item.check_type,
        "params": item.params,
        "interval_secs": item.interval_secs,
    }


async def run_immediate_check(db: Session, monitor_id: int) -> CheckDispatch:
    """Ask for a check now, from whichever vantage the monitor names.

    Server monitors keep exactly today's behaviour: publish to `mon.poll.item`
    and answer 200 regardless — the poll worker owns the outcome from there.

    An agent-assigned monitor is prechecked against §2's six preconditions
    *before* the async hop, because a fire-and-forget publish cannot report that
    the agent is offline, and answering 200 while nothing runs is worse than a
    409. On success it opens a run exactly as the scheduler does and publishes
    nothing but that run's id (§2), leaving the dispatcher to load the host,
    config and credentials immediately before encrypted delivery.
    """
    item = db.get(MonitorItem, monitor_id)
    if item is None:
        return CheckDispatch(ok=False, found=False)

    if item.probe_agent_id is None:
        await nats_client.js_publish(MONITOR_POLL_ITEM, _poll_payload(item))
        return CheckDispatch(ok=True)

    from app.services.monitoring import probe_eligibility, scheduler

    decision = await probe_eligibility.evaluate_eligibility(db, item)
    if not decision.ok:
        return CheckDispatch(ok=False, reason=decision.reason)

    # The same run-opening path the scheduler uses, so a manual check and a due
    # check are indistinguishable downstream and derive one deadline from the
    # monitor's own configured budget.
    run_id = scheduler._create_probe_run(
        db, _poll_payload(item) | {"probe_agent_id": item.probe_agent_id}
    )
    if run_id is None:
        return CheckDispatch(ok=False, reason=probe_eligibility.REASON_PREVIOUS_RUN_IN_FLIGHT)
    undelivered = await _dispatch_probe_run(db, item, run_id)
    if undelivered is not None:
        # The run has been closed again, so this is a refusal like any other:
        # §2's "accepted" claim has to survive the broker being down too.
        return CheckDispatch(ok=False, reason=undelivered)
    return CheckDispatch(ok=True)


# ── Target-scoped monitors (inventory pages, map, discovery) ──────────────────
# One monitor "target" is an inventory entity: a hardware node, a compute unit,
# a service, or an external node. Resolving one yields everything needed to spin
# up a sensible default monitor for it. Drives the inventory list pages, the
# detail drawers, the map, and discovery auto-monitoring.

_DEFAULT_ICMP_CONFIG = {"packet_count": 5}


class TargetInfo(NamedTuple):
    """A probeable inventory entity, reduced to what a monitor needs."""

    label: str
    host: str
    check_type: str
    config: dict


def _resolve_hardware(db: Session, target_id: int) -> TargetInfo | None:
    hw = db.get(Hardware, target_id)
    if hw is None:
        return None
    host = hw.ip_address or hw.hostname
    if not host:
        return None
    label = hw.name or hw.hostname or host
    return TargetInfo(label, host, "icmp", dict(_DEFAULT_ICMP_CONFIG))


def _resolve_compute_unit(db: Session, target_id: int) -> TargetInfo | None:
    cu = db.get(ComputeUnit, target_id)
    if cu is None or not cu.ip_address:
        return None
    return TargetInfo(cu.name or cu.ip_address, cu.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG))


def _resolve_external_node(db: Session, target_id: int) -> TargetInfo | None:
    """External nodes keep an IP *or* a hostname in ip_address — both probe the same."""
    node = db.get(ExternalNode, target_id)
    if node is None or not node.ip_address:
        return None
    return TargetInfo(
        node.name or node.ip_address, node.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG)
    )


def _service_port(svc: Service) -> int | None:
    """First port declared on a service — structured ports_json wins over free text."""
    try:
        entries = json.loads(svc.ports_json) if svc.ports_json else []
    except (TypeError, ValueError):
        entries = []
    for entry in entries if isinstance(entries, list) else []:
        port = entry.get("port") if isinstance(entry, dict) else entry
        try:
            if port is not None and 1 <= int(port) <= 65535:
                return int(port)
        except (TypeError, ValueError):
            continue
    # Free-text fallback: "8080", "8080/tcp", "80,443", "8080:80"
    for chunk in re.split(r"[,\s]+", svc.ports or ""):
        digits = chunk.split(":")[0].split("/")[0]
        if digits.isdigit() and 1 <= int(digits) <= 65535:
            return int(digits)
    return None


def _resolve_service(db: Session, target_id: int) -> TargetInfo | None:
    svc = db.get(Service, target_id)
    if svc is None:
        return None
    label = svc.name or svc.slug
    if svc.url:
        host = urlparse(svc.url).hostname or svc.ip_address
        if host:
            return TargetInfo(label, host, "http", {"url": svc.url})
    if svc.ip_address:
        port = _service_port(svc)
        if port is not None:
            return TargetInfo(label, svc.ip_address, "tcp", {"port": port})
        return TargetInfo(label, svc.ip_address, "icmp", dict(_DEFAULT_ICMP_CONFIG))
    return None


_TARGET_RESOLVERS = {
    "hardware": _resolve_hardware,
    "compute_unit": _resolve_compute_unit,
    "service": _resolve_service,
    "external_node": _resolve_external_node,
}


def resolve_target(db: Session, target_type: str, target_id: int) -> TargetInfo | None:
    """Return probe details for an inventory entity, or None if it can't be probed."""
    resolver = _TARGET_RESOLVERS.get(target_type)
    return resolver(db, target_id) if resolver else None


def _target_monitors(db: Session, target_type: str, target_id: int) -> list[MonitorItem]:
    return list(
        db.scalars(
            select(MonitorItem)
            .where(
                MonitorItem.target_type == target_type,
                MonitorItem.target_id == target_id,
            )
            .order_by(MonitorItem.id)
        ).all()
    )


def _build_target_monitor(
    db: Session,
    target_type: str,
    target_id: int,
    check_type: str | None = None,
    config: dict | None = None,
) -> MonitorItem | None:
    """Add a default monitor for an inventory entity — flushes, does NOT commit.

    Idempotent per (target_type, target_id, check_type): an existing monitor is
    returned untouched. Returns None when the target is unknown or has no address
    to probe. Callers that own the surrounding transaction (discovery merge) use
    this directly; everyone else goes through create_target_monitor().
    """
    info = resolve_target(db, target_type, target_id)
    if info is None:
        return None
    check_type = check_type or info.check_type
    if config is not None:
        # Same per-type validation the generic create path applies.
        params = CONFIG_MODELS[check_type](**config).model_dump(exclude_unset=True)
    else:
        # The resolver's config only describes its own check type.
        params = dict(info.config) if check_type == info.check_type else {}
    existing = db.scalars(
        select(MonitorItem).where(
            MonitorItem.target_type == target_type,
            MonitorItem.target_id == target_id,
            MonitorItem.check_type == check_type,
        )
    ).first()
    if existing is not None:
        return existing
    item = MonitorItem(
        name=f"{info.label} ({check_type})",
        check_type=check_type,
        host=info.host,
        params=params,
        interval_secs=60,
        max_retries=0,
        enabled=True,
        target_type=target_type,
        target_id=target_id,
        last_status=PENDING,
        next_due_at=datetime.now(UTC),
    )
    db.add(item)
    db.flush()
    return item


def create_target_monitor(
    db: Session,
    target_type: str,
    target_id: int,
    check_type: str | None = None,
    config: dict | None = None,
) -> dict | None:
    """Quick-create a default monitor for an inventory entity and commit it."""
    item = _build_target_monitor(db, target_type, target_id, check_type, config)
    if item is None:
        return None
    db.commit()
    db.refresh(item)
    return _to_dict(item, probe_agents=_probe_agents(db, [item]))


def set_target_paused(db: Session, target_type: str, target_id: int, paused: bool) -> bool:
    """Pause/resume every monitor attached to an inventory entity."""
    items = _target_monitors(db, target_type, target_id)
    if not items:
        return False
    now = datetime.now(UTC)
    cancellation = (
        cancel_monitor_probe_runs(db, [i.id for i in items], reason=CANCEL_MONITOR_PAUSED)
        if paused
        else ProbeCancellation()
    )
    for item in items:
        item.enabled = not paused
        if not paused:
            item.next_due_at = now
        db.add(
            MonitorEvent(
                item_id=item.id,
                event_type="paused" if paused else "resumed",
                status_from=item.last_status,
                status_to=item.last_status or PENDING,
                msg="paused by user" if paused else "resumed by user",
            )
        )
    db.commit()
    schedule_probe_cancels(cancellation)
    return True


async def run_target_check(db: Session, target_type: str, target_id: int) -> bool:
    """Publish an immediate check for every monitor attached to an inventory entity.

    Each monitor goes to its own vantage. §2 allows no automatic fallback, so an
    agent-assigned monitor gets a run and a `mon.probe.remote` publication here
    exactly as it would from the scheduler — publishing it to `mon.poll.item`
    would have the server silently execute a check the operator assigned to an
    agent. Eligibility is left to the dispatcher, which re-checks it and closes
    the run with a reason if the vantage cannot take the work; this path answers
    for a whole target, so there is no single reason it could return.

    Async for the same reason `run_immediate_check` is (D-14): both publishes
    have to actually happen before the response. A `def` route runs in FastAPI's
    threadpool, where there is no event loop for `_publish_soon` to schedule on —
    it would open a run, publish nothing, and answer 200, leaving the monitor
    wedged behind its own queued run until the reconciliation pass expired it.

    Returns False only when the target has no monitors at all — the 404 the
    inventory routes render.
    """
    items = _target_monitors(db, target_type, target_id)
    if not items:
        return False
    from app.services.monitoring import scheduler

    for item in items:
        if item.probe_agent_id is None:
            await nats_client.js_publish(MONITOR_POLL_ITEM, _poll_payload(item))
            continue
        run_id = scheduler._create_probe_run(
            db, _poll_payload(item) | {"probe_agent_id": item.probe_agent_id}
        )
        if run_id is None:
            continue
        await _dispatch_probe_run(db, item, run_id)
    return True


def list_target_summaries(
    db: Session, target_type: str, target_ids: list[int] | None = None
) -> list[dict]:
    """One rollup row per inventory entity that has monitors, for the list pages."""
    query = select(MonitorItem).where(MonitorItem.target_type == target_type)
    if target_ids is not None:
        if not target_ids:
            return []
        query = query.where(MonitorItem.target_id.in_(target_ids))
    items = list(db.scalars(query.order_by(MonitorItem.id)).all())
    if not items:
        return []

    uptimes = _uptime_pct_map(db, [i.id for i in items])
    latencies = _latest_metric_map(db, [i.id for i in items], "latency_ms")

    grouped: dict[int, list[MonitorItem]] = {}
    for item in items:
        if item.target_id is not None:
            grouped.setdefault(item.target_id, []).append(item)

    agents = _probe_agents(db, [group[0] for group in grouped.values()])

    summaries = []
    for target_id, group in grouped.items():
        primary = group[0]  # lowest id — the monitor auto-created for this target
        statuses = {i.last_status or PENDING for i in group}
        if "down" in statuses:
            status = "down"
        elif "up" in statuses:
            status = "up"
        else:
            status = primary.last_status or PENDING
        summaries.append(
            {
                **_probe_block(primary, agents),
                "target_type": target_type,
                "target_id": target_id,
                "monitor_id": primary.id,
                "monitor_ids": [i.id for i in group],
                "enabled": any(i.enabled for i in group),
                "status": status,
                "latency_ms": latencies.get(primary.id),
                "uptime_pct_24h": uptimes.get(primary.id),
                "last_polled_at": max(
                    (i.last_polled_at for i in group if i.last_polled_at is not None),
                    default=None,
                ),
            }
        )
    return summaries
