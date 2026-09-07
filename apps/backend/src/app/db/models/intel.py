"""Derived analytics: capacity forecasts, efficiency recommendations, flap incidents and
the CVE catalog.
"""

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

from app.core.time import utcnow
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.hardware import Hardware

# ── CVE Entries (stored in separate cve.db) ──────────────────────────────────


class CVEEntry(Base):
    """NVD/CVE records kept in a dedicated SQLite database (data/cve.db).

    The table is created by ``cve_session.init_cve_db()``; it also lives in the
    main Base metadata so ``create_all`` on the primary DB is a safe no-op (the
    table simply won't be populated there).
    """

    __tablename__ = "cve_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String, index=True)
    product: Mapped[str | None] = mapped_column(String, index=True)
    version_start: Mapped[str | None] = mapped_column(String)
    version_end: Mapped[str | None] = mapped_column(String)
    severity: Mapped[str | None] = mapped_column(String)  # low / medium / high / critical
    cvss_score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Intelligence / Analytics ──────────────────────────────────────────────────


class CapacityForecast(Base):
    __tablename__ = "capacity_forecasts"
    __table_args__ = (
        UniqueConstraint("hardware_id", "metric", name="uq_capacity_forecast_hw_metric"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    slope_per_day: Mapped[float] = mapped_column(Float, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, nullable=False)
    projected_full_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    warning_threshold_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="capacity_forecasts")


class ResourceEfficiencyRecommendation(Base):
    __tablename__ = "resource_efficiency_recommendations"
    __table_args__ = (
        UniqueConstraint("asset_type", "asset_id", name="uq_resource_efficiency_asset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    cpu_avg_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_peak_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_avg_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FlapIncident(Base):
    __tablename__ = "flap_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transition_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
