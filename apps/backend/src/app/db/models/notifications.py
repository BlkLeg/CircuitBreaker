"""Where notifications go, and which events route to which sink."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

# ── Notifications ──────────────────────────────────────────────────


class NotificationSink(Base):
    __tablename__ = "notification_sinks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)  # 'slack', 'email', 'teams'
    provider_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Routing config plus credentials. Secret keys are stored Fernet-encrypted
    # under an "<key>_enc" sibling (e.g. webhook_url_enc) — see
    # services/notification_secrets.py, which is also the only place that
    # decides which keys count as secret.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NotificationRoute(Base):
    __tablename__ = "notification_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sink_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notification_sinks.id"), nullable=False
    )
    alert_severity: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'info', 'warning', 'critical'
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    sink: Mapped["NotificationSink"] = relationship("NotificationSink")


class NotificationDelivery(Base):
    """Retry-safe per-event, per-destination delivery receipt.

    This stores only operational disposition. Alert payloads and destination
    credentials remain outside the table.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("event_id", "sink_key", name="uq_notification_delivery_event_sink"),
        Index("ix_notification_deliveries_state_retry", "state", "next_retry_at"),
        Index("ix_notification_deliveries_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    # Immutable identity snapshot. sink_id may become NULL after destination
    # deletion, but sink_key keeps replay uniqueness intact.
    sink_key: Mapped[int] = mapped_column(Integer, nullable=False)
    sink_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("notification_sinks.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    safe_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_after_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
