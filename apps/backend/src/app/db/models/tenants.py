"""The multi-tenancy tables. Tenancy is a 410 stub for the single-tenant 1.0 contract; the
schema is kept so enabling it later is not a migration of live data.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.auth import User

# ── Tenants (Multi-Tenancy) ───────────────────────────────────────────────────


tenant_members = Table(
    "tenant_members",
    Base.metadata,
    Column("tenant_id", Integer, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_role", String(20), nullable=False, default="member"),
)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    slug: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    members: Mapped[list["User"]] = relationship(
        "User", secondary=tenant_members, backref="tenants"
    )
