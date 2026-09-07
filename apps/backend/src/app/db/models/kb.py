"""The offline knowledge base discovery fingerprints against: OUI to vendor, hostname to
device hints.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._shared import _now
from app.db.session import Base

# ── Knowledge Base: OUI → Vendor ──────────────────────────────────────────────


class KbOui(Base):
    """Learned + manually added MAC OUI → vendor mappings."""

    __tablename__ = "kb_oui"

    prefix: Mapped[str] = mapped_column(String(6), primary_key=True)  # e.g. "BC2411"
    vendor: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(  # "learned" | "manual"
        String(32), nullable=False, default="learned"
    )
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


# ── Knowledge Base: Hostname → Device Hints ───────────────────────────────────


class KbHostname(Base):
    """Learned + manually added hostname pattern → device hints."""

    __tablename__ = "kb_hostname"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(128), nullable=False)
    match_type: Mapped[str] = mapped_column(  # "prefix" | "exact" | "contains"
        String(32), nullable=False, default="prefix"
    )
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(  # "learned" | "manual"
        String(32), nullable=False, default="learned"
    )
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )
