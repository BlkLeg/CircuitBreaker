"""Where notifications go, and which events route to which sink."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
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
