"""Cache-only models for the normalized vulnerability feed.

These tables deliberately use metadata separate from the application's
PostgreSQL ``Base``.  They are created and upgraded only by
``app.db.cve_session`` inside the disposable SQLite CVE cache.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class CVECacheBase(DeclarativeBase):
    pass


class CVECacheSchema(CVECacheBase):
    __tablename__ = "cve_cache_schema"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CVEFeedGeneration(CVECacheBase):
    __tablename__ = "cve_feed_generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="nvd")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_records: Mapped[int | None] = mapped_column(Integer)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_stored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    safe_error: Mapped[str | None] = mapped_column(String(300))

    records: Mapped[list[CVENormalizedRecord]] = relationship(
        back_populates="generation", cascade="all, delete-orphan"
    )


class CVENormalizedRecord(CVECacheBase):
    __tablename__ = "cve_normalized_records"
    __table_args__ = (
        Index("uq_cve_normalized_generation_cve", "generation_id", "cve_id", unique=True),
        Index("ix_cve_normalized_generation_score", "generation_id", "cvss_score"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    generation_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("cve_feed_generations.id", ondelete="CASCADE"), nullable=False
    )
    cve_id: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16))
    cvss_score: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configurations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    generation: Mapped[CVEFeedGeneration] = relationship(back_populates="records")
    applicability: Mapped[list[CVEApplicability]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class CVEApplicability(CVECacheBase):
    __tablename__ = "cve_applicability"
    __table_args__ = (
        Index("ix_cve_applicability_vendor_product", "vendor", "product"),
        Index("ix_cve_applicability_record", "record_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cve_normalized_records.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(160), nullable=False)
    criteria: Mapped[str] = mapped_column(Text, nullable=False)
    vulnerable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    part: Mapped[str | None] = mapped_column(String(8))
    vendor: Mapped[str | None] = mapped_column(String(255))
    product: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(255))
    version_start_including: Mapped[str | None] = mapped_column(String(255))
    version_start_excluding: Mapped[str | None] = mapped_column(String(255))
    version_end_including: Mapped[str | None] = mapped_column(String(255))
    version_end_excluding: Mapped[str | None] = mapped_column(String(255))

    record: Mapped[CVENormalizedRecord] = relationship(back_populates="applicability")
