"""VMs and containers, and the two taxonomies every entity can be filed under."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _FK_HARDWARE_ID, _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.hardware import Hardware
    from app.db.models.networks import ComputeNetwork
    from app.db.models.services import Service

# ── Compute Units ───────────────────────────────────────────────────────────


class ComputeUnit(Base):
    __tablename__ = "compute_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'vm' | 'container'
    hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False)
    os: Mapped[str | None] = mapped_column(String)
    icon_slug: Mapped[str | None] = mapped_column(String)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, name="CPU_cores")
    cpu_brand: Mapped[str | None] = mapped_column(String)
    memory_mb: Mapped[int | None] = mapped_column(Integer)
    disk_gb: Mapped[int | None] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String)
    download_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    environment: Mapped[str | None] = mapped_column(String)
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("environments.id"), nullable=True
    )
    # v0.1.4-cortex: derived status from child services
    status: Mapped[str | None] = mapped_column(String, nullable=True, default="unknown")
    status_override: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text)
    # v0.2.0: Proxmox integration (JSONB)
    proxmox_vmid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proxmox_type: Mapped[str | None] = mapped_column(String, nullable=True)  # "qemu" | "lxc"
    proxmox_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    proxmox_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    integration_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("integration_configs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="compute_units")
    environment_rel: Mapped["Environment | None"] = relationship(
        "Environment", back_populates="compute_units", foreign_keys=[environment_id]
    )
    services: Mapped[list["Service"]] = relationship("Service", back_populates="compute_unit")
    network_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="compute_unit"
    )


# ── Categories ──────────────────────────────────────────────────────────────


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    services: Mapped[list["Service"]] = relationship("Service", back_populates="category_rel")


# ── Environments ─────────────────────────────────────────────────────────────


class Environment(Base):
    __tablename__ = "environments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    hardware: Mapped[list["Hardware"]] = relationship("Hardware", back_populates="environment_rel")
    compute_units: Mapped[list["ComputeUnit"]] = relationship(
        "ComputeUnit", back_populates="environment_rel"
    )
    services: Mapped[list["Service"]] = relationship("Service", back_populates="environment_rel")
