"""Privacy posture scoring and the findings an operator has chosen to ignore."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
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


class PrivacyScoreHistory(Base):
    """Historical record of privacy scores and threat profiles."""

    __tablename__ = "privacy_score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    threat_profile: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="privacy_history")


class NetworkPrivacySnapshot(Base):
    """Point-in-time network privacy score with its deductions and check results."""

    __tablename__ = "network_privacy_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[str] = mapped_column(String(1), nullable=False)
    deductions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    checks: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class PrivacyFindingIgnore(Base):
    """An admin's decision to suppress one privacy finding from scoring.

    ``hardware_id`` is null for network-level findings (the DNS/captive-portal
    checks); set for device rule findings (telnet_open, etc).
    """

    __tablename__ = "privacy_finding_ignores"
    __table_args__ = (
        # Postgres treats every NULL as distinct, so the composite unique
        # constraint alone would allow duplicate ignores for network-level
        # findings (hardware_id is null there) — the partial index below
        # covers that case.
        UniqueConstraint("rule_id", "hardware_id", name="uq_privacy_ignore_rule_hw"),
        Index(
            "uq_privacy_ignore_rule_network",
            "rule_id",
            unique=True,
            postgresql_where=text("hardware_id IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="CASCADE"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
