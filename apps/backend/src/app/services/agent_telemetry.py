from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.redis import get_redis
from app.core.time import utcnow
from app.db.models import (
    Agent,
    AgentCapabilityReadiness,
    AgentHostSample,
    Hardware,
    HardwareLiveMetric,
)
from app.schemas.agent_frame import CapabilityReadinessPayload, HostTelemetryPayload
from app.services.agent_registry import record_network_facts
from app.services.telemetry_cache import cache_telemetry, publish_telemetry
from app.services.telemetry_normalize import (
    _NON_LIVE_STATUSES,
    agent_summary_to_platform,
    live_metric_fields,
)

_SAMPLE_ID = re.compile(r"^[0-9a-f]{32}$")
_logger = logging.getLogger(__name__)
_MAX_PAYLOAD = 256 << 10
_LIST_LIMITS = {"filesystems": 128, "disks": 128, "interfaces": 128, "temperatures": 256}
_PERCENT_FIELDS = {"cpu_pct", "mem_pct", "swap_pct", "root_disk_pct"}
# The complete readiness vocabulary; anything else is a protocol violation.
# Slice 3 probe collectors and slice 4 discovery collectors reuse these four.
_READINESS_STATES = frozenset({"ready", "degraded", "unavailable", "disabled"})
_violation_lock = threading.Lock()
_violations: dict[int, tuple[float, int]] = {}


class InvalidHostTelemetry(ValueError):
    pass


def recordable_violation(agent_id: int) -> tuple[bool, int]:
    """Rate-limit payload-free audit events while retaining repeat counts."""
    now = time.monotonic()
    with _violation_lock:
        last, count = _violations.get(agent_id, (0.0, 0))
        count += 1
        if now - last >= 60:
            _violations[agent_id] = (now, 0)
            return True, count
        _violations[agent_id] = (last, count)
        return False, count


def validate_host_payload(payload: dict[str, Any], collected_at: datetime) -> HostTelemetryPayload:
    if len(json.dumps(payload, separators=(",", ":")).encode()) > _MAX_PAYLOAD:
        raise InvalidHostTelemetry("payload exceeds 256 KiB")
    try:
        sample = HostTelemetryPayload.model_validate(payload)
    except ValidationError as exc:
        raise InvalidHostTelemetry("payload schema is invalid") from exc
    if sample.schema_version != 1 or sample.status not in {"healthy", "degraded"}:
        raise InvalidHostTelemetry("unsupported schema or status")
    if not _SAMPLE_ID.fullmatch(sample.sample_id):
        raise InvalidHostTelemetry("sample_id must be 128-bit lowercase hex")
    for field, limit in _LIST_LIMITS.items():
        if len(getattr(sample, field)) > limit:
            raise InvalidHostTelemetry(f"{field} exceeds {limit} entries")
    for name, value in sample.summary.items():
        # The `isinstance(value, bool)` half of this guard cannot fire:
        # HostTelemetryPayload types summary as `dict[str, int | float]`
        # (schemas/agent_frame.py), and pydantic coerces a JSON `true` to
        # int 1 before this loop ever runs — so a boolean is accepted as 1.
        # Pinned by test_boolean_summary_value_is_coerced_to_one_and_accepted.
        # Rejecting booleans would need a field_validator on `summary`.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidHostTelemetry(f"summary.{name} is not numeric")
        if name in _PERCENT_FIELDS and not 0 <= value <= 100:
            raise InvalidHostTelemetry(f"summary.{name} is outside 0..100")
        if name not in _PERCENT_FIELDS and value < 0:
            raise InvalidHostTelemetry(f"summary.{name} is negative")
    now = utcnow()
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=UTC)
    if collected_at > now + timedelta(seconds=60):
        raise InvalidHostTelemetry("collection timestamp is in the future")
    if collected_at < now - timedelta(days=30):
        raise InvalidHostTelemetry("collection timestamp is outside retention")
    return sample


async def ingest_host_sample(
    db: Session, agent: Agent, payload: dict[str, Any], collected_at: datetime
) -> AgentHostSample:
    if agent.status != "active":
        raise InvalidHostTelemetry("agent is not active")
    sample = validate_host_payload(payload, collected_at)
    existing = db.execute(
        select(AgentHostSample).where(
            AgentHostSample.agent_id == agent.id,
            AgentHostSample.sample_id == sample.sample_id,
            AgentHostSample.collected_at == collected_at,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    summary = sample.summary
    row = AgentHostSample(
        agent_id=agent.id,
        hardware_id=agent.hardware_id,
        sample_id=sample.sample_id,
        collected_at=collected_at,
        status=sample.status,
        raw=payload,
        cpu_pct=summary.get("cpu_pct"),
        mem_pct=summary.get("mem_pct"),
        root_disk_pct=summary.get("root_disk_pct"),
        net_rx_bps=summary.get("net_rx_bps"),
        net_tx_bps=summary.get("net_tx_bps"),
        max_temp_c=summary.get("max_temp_c"),
        load_1=summary.get("load_1"),
        uptime_s=summary.get("uptime_s"),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Exactly one integrity failure is recoverable here: another writer
        # committed this (agent_id, sample_id, collected_at) between our SELECT
        # and our INSERT, so `uq_agent_host_sample` rejected the duplicate and
        # the winner's row is what the caller wants.  Confirming the row is
        # actually there is what distinguishes that case -- driver-agnostically,
        # without decoding a SQLSTATE -- from a genuine schema/constraint fault
        # (a NotNullViolation from a missing id sequence, an FK violation).
        # Swallowing those and then failing in this SELECT reported them as an
        # unrelated `NoResultFound` and took the /link socket down with it.
        db.rollback()
        existing = db.execute(
            select(AgentHostSample).where(
                AgentHostSample.agent_id == agent.id,
                AgentHostSample.sample_id == sample.sample_id,
                AgentHostSample.collected_at == collected_at,
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
        return existing
    # One normalizer: the Hardware-facing surfaces (the live-metric row,
    # `telemetry_data`, and the cache/WebSocket envelope below) all speak the
    # platform vocabulary produced here, never the agent's own key names. The
    # agent names stay on `agent_host_samples` and the Agent-detail API.
    platform = agent_summary_to_platform(summary, sample.filesystems)
    project_live = False
    if row.hardware_id is not None:
        metric = HardwareLiveMetric(
            hardware_id=row.hardware_id,
            agent_id=agent.id,
            agent_sample_id=row.sample_id,
            collected_at=collected_at,
            **live_metric_fields(platform),
            status=sample.status,
            source="agent",
            raw=platform,
        )
        db.add(metric)
        row.projected_at = utcnow()
        hardware = db.get(Hardware, row.hardware_id)
        if hardware is not None and (
            hardware.telemetry_last_polled is None or collected_at >= hardware.telemetry_last_polled
        ):
            project_live = True
            hardware.telemetry_data = platform
            hardware.telemetry_status = sample.status
            hardware.telemetry_last_polled = collected_at
            # Matches the poller paths: a non-live status must not advance
            # `last_seen`. Unobservable while the agent vocabulary is
            # {healthy, degraded}; locked shut before that vocabulary grows.
            if sample.status not in _NON_LIVE_STATUSES:
                hardware.last_seen = collected_at.isoformat()
    db.commit()
    redis = await get_redis()
    if redis is not None:
        try:
            await redis.publish(
                f"telemetry:agent:{agent.id}",
                json.dumps(
                    {
                        "type": "telemetry.host",
                        "agent_id": agent.id,
                        "collected_at": collected_at.isoformat(),
                        "payload": payload,
                    }
                ),
            )
        except Exception as exc:
            _logger.debug("agent telemetry publish failed: %s", exc)
    if row.hardware_id is not None and project_live:
        hardware_payload = {
            "data": platform,
            "status": sample.status,
            "last_polled": collected_at.isoformat(),
            "source": "agent",
            "agent_id": agent.id,
            "sample_id": sample.sample_id,
        }
        try:
            await cache_telemetry(row.hardware_id, hardware_payload, ttl=60)
            await publish_telemetry(
                row.hardware_id,
                {"entity_type": "hardware", "hardware_id": row.hardware_id, **hardware_payload},
            )
        except Exception as exc:
            _logger.debug("agent Hardware telemetry publish failed: %s", exc)
    return row


async def ingest_readiness(db: Session, agent: Agent, payload: dict[str, Any]) -> bool:
    """Upsert one `agent_capability_readiness` row per reported collector.

    **All-or-nothing.** Every `state` in the report is validated against
    `_READINESS_STATES` *before* the upsert loop performs any `db.get`,
    `db.add`, or attribute write, so a report carrying one bad entry persists
    nothing at all — not even the entries that preceded it. The pre-pass, not a
    rollback in the caller, is what guarantees this: `_handle_readiness`
    (services/agent_link.py) catches `InvalidHostTelemetry`, records a
    `protocol_violation` event and then commits, which would otherwise make a
    partial write durable. Direct callers get the same guarantee, and none of
    the caller's other pending work is discarded.

    A report may also carry `networks` (D-8), which is forwarded to
    `agent_registry.record_network_facts` inside this same transaction — after
    the validation pre-pass, so a report rejected for a bad `state` refreshes no
    scope either. See the comment at the forward for why the gate is the key's
    presence rather than its truthiness, and the comment at the publish for why
    the `discovery.cancel` frames a moved scope produces go out only after the
    commit below returns.
    """
    try:
        report = CapabilityReadinessPayload.model_validate(payload)
    except ValidationError as exc:
        raise InvalidHostTelemetry("invalid readiness payload") from exc
    for item in report.readiness:
        if item.state not in _READINESS_STATES:
            raise InvalidHostTelemetry("invalid readiness state")
    changed = False
    now = utcnow()
    for item in report.readiness:
        row = db.get(AgentCapabilityReadiness, (agent.id, item.collector))
        values = (item.state, item.reason, item.remediation, item.missing)
        if row is None:
            row = AgentCapabilityReadiness(agent_id=agent.id, collector=item.collector)
            db.add(row)
            changed = True
        elif (row.state, row.reason, row.remediation, row.missing) != values:
            changed = True
        row.state, row.reason, row.remediation, row.missing, row.updated_at = (*values, now)
    # D-8: `networks` is the one optional field this frame gained, and it exists
    # only to refresh `agent_networks` *mid-session* — `hello.networks` is sent
    # at connect, so a subnet that appeared on the agent host would otherwise
    # not become discoverable until the next reconnect. The facts keep living in
    # `agent_networks.facts` (the sole input to `core.agent_scope.derive_scope`)
    # rather than in an `agent_capability_readiness` column, so there is no
    # second copy of the scope to disagree.
    #
    # Gated on *presence*, never truthiness, which is the rule
    # `record_network_facts` documents: an agent build predating the field omits
    # the key entirely and must leave the last known report standing, while an
    # explicit `[]` is a real report of "nothing directly connected" and must
    # replace it — an agent that has lost every usable interface must be able to
    # say so, or the server keeps enforcing a stale, wider-than-reality scope
    # forever and the generation in-flight work is cancelled on never moves.
    #
    # The forward lands *before* the commit below, so the refreshed scope and
    # the readiness report it arrived with are one transaction: no reader can
    # observe a `generation` bump whose readiness rows never landed, or the
    # reverse. `record_network_facts` deliberately owns no commit of its own.
    #
    # It does not feed `changed`, which stays the readiness-row question the
    # publish below fans out — that message carries readiness rows only, and
    # scope consumers already have `agent_networks.generation`.
    scope_cancellation = None
    if "networks" in report.model_fields_set:
        scope_cancellation = record_network_facts(db, agent, report.networks)
    db.commit()
    if scope_cancellation:
        # D-16, and the ordering `agent_discovery`'s cancellation section makes
        # a rule for every trigger: the doomed dispatches were closed above,
        # inside the transaction, and the agent is told to abandon them only
        # once that transaction is durable. Published from here rather than
        # from `record_network_facts` because a `discovery.cancel` sent before
        # the commit that closes its job is one the commit failing un-does —
        # the agent stops sweeping while the server still shows the job live.
        # `publish_discovery_cancels` never raises, so an agent that vanished
        # cannot take down the /link read loop this runs on. Imported here
        # because `agent_discovery` imports this module at its own module scope.
        from app.services.agent_discovery import publish_discovery_cancels

        await publish_discovery_cancels(scope_cancellation)
    if changed:
        redis = await get_redis()
        if redis is not None:
            await redis.publish(
                f"telemetry:agent:{agent.id}",
                json.dumps(
                    {
                        "type": "capability.readiness",
                        "agent_id": agent.id,
                        "readiness": [x.model_dump() for x in report.readiness],
                    },
                    default=str,
                ),
            )
    return changed
