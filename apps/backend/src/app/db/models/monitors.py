"""Uptime monitoring: what is checked, each probe run, and the rollups read by the UI."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _FK_HARDWARE_ID, _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.hardware import Hardware

# ── Uptime Monitoring ────────────────────────────────────────────────────────


class HardwareMonitor(Base):
    """One monitoring config row per hardware device."""

    __tablename__ = "hardware_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), unique=True, nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # JSON array: ["icmp","tcp","http","snmp"] — JSONB as of v0.2.0
    probe_methods: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=lambda: ["icmp", "tcp", "http"]
    )
    last_status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    last_checked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="monitor")


class MonitorItem(Base):
    """A monitor: one configured check on a target at an interval."""

    __tablename__ = "monitor_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, default="", server_default="")
    # hardware|compute_unit|external_node|service|ip — None for standalone monitors
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    host: Mapped[str] = mapped_column(String, nullable=False)  # resolved ip/hostname to probe
    check_type: Mapped[str] = mapped_column(String, nullable=False)  # icmp|tcp|http|dns
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # interval while in pending (retrying); None falls back to interval_secs
    retry_interval_secs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # up|down|pending|maintenance
    last_status: Mapped[str | None] = mapped_column(String, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    # Slice 3 §1: the vantage. NULL is server execution — today's behaviour and
    # the only value any pre-Slice-3 monitor has. RESTRICT, unlike every other
    # agents FK in this module, because unassigning a monitor is a decision the
    # user makes explicitly; deleting the agent must fail with 409 instead of
    # silently moving its monitors back to the server.
    probe_agent_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("agents.id", ondelete="RESTRICT", name="fk_monitor_items_probe_agent_id_agents"),
        nullable=True,
    )
    # ready|queued|running|unavailable|stale — whether the *vantage* can run the
    # check, which is orthogonal to `last_status` (whether the target is up).
    # NULL while the monitor executes on the server.
    probe_execution_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Why the vantage is in that state: agent_offline, capability_disabled,
    # out_of_scope, dispatch_failed, result_timeout, previous_run_in_flight, …
    probe_execution_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    probe_last_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    probe_last_result_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_monitor_items_due", "enabled", "next_due_at"),
        # Serves both the per-vantage assignment listings and the scheduler's
        # oversampled fair-share claim (D-2), whose ORDER BY would otherwise
        # degrade to a full sort over every due row.
        Index("ix_monitor_items_probe_due", "probe_agent_id", "enabled", "next_due_at"),
    )


class MonitorEvent(Base):
    """State-transition history for a monitor (feeds event log and check bar)."""

    __tablename__ = "monitor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitor_items.id", ondelete="CASCADE"), nullable=False
    )
    # up|down|pending|maintenance|paused|resumed
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    status_from: Mapped[str | None] = mapped_column(String, nullable=True)
    status_to: Mapped[str] = mapped_column(String, nullable=False)
    msg: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # seconds spent in status_from before this transition
    duration_secs: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_monitor_events_item_time", "item_id", "created_at"),)


class MonitorProbeRun(Base):
    """One remote check handed to an agent — the durable lease behind it (§1).

    A run exists from the moment the scheduler decides an agent-assigned monitor
    is due until a `probe.result` lands, the deadline passes, or it is cancelled.
    It is the audit record for a check the server did not perform itself, and the
    only place `CheckResult.details` and per-sample `error_reason` are persisted:
    `telemetry_timeseries` deliberately keeps neither for server-executed checks
    (D-8), and adding them there would mean altering a compressed hypertable for
    metadata monitor state does not depend on.

    Retention is seven days; long-term availability stays in
    `telemetry_timeseries` and the monitor rollups.
    """

    __tablename__ = "monitor_probe_runs"

    # Deliberately a plain single-column PK: this is not a hypertable, and the
    # composite `(id, <time>)` shape the Timescale tables use is what made
    # SQLAlchemy decline to emit a sequence in the 0001 bootstrap (F-7).
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # Opaque random 128-bit token. It is the only identifier that travels to the
    # agent, so a leaked or guessed monitor id cannot be used to post a result.
    run_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    monitor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitor_items.id", ondelete="CASCADE"), nullable=False
    )
    # CASCADE, unlike `monitor_items.probe_agent_id` above: the RESTRICT there
    # already blocks deleting an agent that still holds assignments, so anything
    # reachable here is finished history, not a live vantage.
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    # queued|dispatched|completed|execution_error|expired|cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # completed|execution_error|cancelled|rejected — what the agent reported,
    # which is not the same question as `status` (where the run got to).
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    msg: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_monitor_probe_runs_agent_status", "agent_id", "status", "scheduled_at"),
        Index("ix_monitor_probe_runs_monitor_time", "monitor_id", "created_at"),
        # One in-flight run per monitor, enforced by the database rather than by
        # whichever caller remembers to look. Partial, because completed history
        # accumulates — a full unique index would wedge the monitor after its
        # first run. This predicate is why `monitor_probe_runs` must stay out of
        # 0001_init's bootstrap: its index-copy loop cannot carry a WHERE clause.
        Index(
            "uq_monitor_probe_runs_active",
            "monitor_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'dispatched')"),
        ),
    )


class UptimeEvent(Base):
    """Rolling history of probe results for a monitored hardware device."""

    __tablename__ = "uptime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)  # "up" | "down"
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    probe_method: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[str] = mapped_column(String, nullable=False)

    hardware: Mapped["Hardware"] = relationship("Hardware")


class MonitorDailyStats(Base):
    """Daily aggregated uptime rollup for a monitor, across every target type."""

    __tablename__ = "monitor_daily_stats"
    __table_args__ = (UniqueConstraint("item_id", "date", name="uq_monitor_daily_stats_item_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monitor_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO date string YYYY-MM-DD
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
