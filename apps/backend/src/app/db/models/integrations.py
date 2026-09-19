"""Third-party monitor sources and the checks they contribute."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.hardware import Hardware
    from app.db.models.services import Service

# ── Integrations ─────────────────────────────────────────────────────────────


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    # integration-specific slug (e.g. status page slug)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sync_interval_s: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), default="never")  # "ok"|"error"|"never"
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    monitors: Mapped[list["IntegrationMonitor"]] = relationship(
        "IntegrationMonitor", back_populates="integration", cascade="all, delete-orphan"
    )


class IntegrationMonitor(Base):
    __tablename__ = "integration_monitors"
    __table_args__ = (UniqueConstraint("integration_id", "external_id", name="uq_intmon_ext_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    integration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # "up"|"down"|"pending"|"maintenance"
    status: Mapped[str] = mapped_column(String(16), default="pending")
    uptime_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cert_expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="SET NULL"), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Native probe configuration (NULL for Uptime Kuma monitors)
    linked_service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    probe_type: Mapped[str | None] = mapped_column(String, nullable=True)  # icmp | http | tcp
    probe_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probe_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    integration: Mapped["Integration"] = relationship("Integration", back_populates="monitors")
    events: Mapped[list["IntegrationMonitorEvent"]] = relationship(
        "IntegrationMonitorEvent", back_populates="monitor", cascade="all, delete-orphan"
    )
    linked_hardware: Mapped["Hardware | None"] = relationship(
        "Hardware", foreign_keys=[linked_hardware_id], back_populates="integration_monitors"
    )
    linked_service: Mapped["Service | None"] = relationship(
        "Service", foreign_keys=[linked_service_id]
    )


class IntegrationMonitorEvent(Base):
    __tablename__ = "integration_monitor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Admin annotation — reason for this state change
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    monitor: Mapped["IntegrationMonitor"] = relationship(
        "IntegrationMonitor", back_populates="events"
    )
