"""Time-series metrics. Retention on the hypertables is a TimescaleDB policy (migration
0050), not a DELETE job.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._shared import _now
from app.db.session import Base

# ── Live Metrics ────────────────────────────────────────────────────────────


class LiveMetric(Base):
    __tablename__ = "live_metrics"

    ip: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str | None] = mapped_column(String)  # e.g., hw-123
    node_type: Mapped[str | None] = mapped_column(String)  # hardware/service
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String)  # up/down/offline
    assigned_to: Mapped[str | None] = mapped_column(String)  # service slug or null
    subnet: Mapped[str | None] = mapped_column(String)  # 10.10.10.0/24


# ── Hardware Live Metrics ───────────────────────────────────────────────────


class HardwareLiveMetric(Base):
    __tablename__ = "hardware_live_metrics"
    # TimescaleDB requires the partitioning (time) column to be part of the PK.
    __table_args__ = (
        PrimaryKeyConstraint("id", "collected_at"),
        Index("ix_hardware_live_metrics_agent_time", "agent_id", "collected_at"),
        Index(
            "uq_hardware_live_metrics_agent_sample",
            "agent_id",
            "agent_sample_id",
            "collected_at",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    agent_sample_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_used_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_total_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Telemetry Timeseries ─────────────────────────────────────────────────────


class TelemetryTimeseries(Base):
    __tablename__ = "telemetry_timeseries"
    # TimescaleDB requires the partitioning (time) column to be part of the PK.
    __table_args__ = (
        PrimaryKeyConstraint("id", "ts"),
        Index("ix_telemetry_timeseries_item_id", "item_id", "metric", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, autoincrement=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # 'hardware' | 'compute_unit'
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)  # 'cpu_pct', 'mem_used_gb', etc.
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True, default="proxmox")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
