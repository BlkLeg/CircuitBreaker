"""Services, the storage they use, freeform items, and the links between them."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _FK_HARDWARE_ID, _FK_SERVICES_ID, _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.compute import Category, ComputeUnit, Environment
    from app.db.models.hardware import Hardware

# ── Services ────────────────────────────────────────────────────────────────


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    compute_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("compute_units.id"), nullable=True
    )
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True
    )
    icon_slug: Mapped[str | None] = mapped_column(String)
    custom_icon: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String)
    ports: Mapped[str | None] = mapped_column(String)
    # Structured port bindings — JSONB as of v0.2.0 (migration 0026 casts this
    # column alongside ip_conflict_json below). The model lagged the migration,
    # so writers handed a list to a Text column and readers json.loads()'d a list
    # psycopg2 had already parsed; both failed silently into empty port lists.
    # none_as_null keeps an unset value a SQL NULL. SQLAlchemy's JSON default
    # would store the *JSON* null instead, which reads back as None but is not
    # NULL to Postgres — silently emptying the `ports_json IS NULL` predicate the
    # legacy-ports backfill selects on, and matching how migration 0026 left
    # already-NULL rows.
    ports_json: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("environments.id"), nullable=True
    )
    status: Mapped[str | None] = mapped_column(String)  # running | stopped | degraded | maintenance
    ip_address: Mapped[str | None] = mapped_column(String)
    # IP conflict classification (host-chain-aware) — JSONB as of v0.2.0
    ip_mode: Mapped[str] = mapped_column(Text, default="explicit", server_default="explicit")
    ip_conflict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    ip_conflict_json: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # Docker container metadata — labels JSONB as of v0.2.0
    docker_container_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    docker_image: Mapped[str | None] = mapped_column(String, nullable=True)
    docker_labels: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_docker_container: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    compute_unit: Mapped["ComputeUnit | None"] = relationship(
        "ComputeUnit", back_populates="services"
    )
    hardware: Mapped["Hardware | None"] = relationship("Hardware")
    category_rel: Mapped["Category | None"] = relationship("Category", back_populates="services")
    environment_rel: Mapped["Environment | None"] = relationship(
        "Environment", back_populates="services", foreign_keys=[environment_id]
    )
    dependencies: Mapped[list["ServiceDependency"]] = relationship(
        "ServiceDependency",
        foreign_keys="ServiceDependency.service_id",
        back_populates="service",
    )
    dependents: Mapped[list["ServiceDependency"]] = relationship(
        "ServiceDependency",
        foreign_keys="ServiceDependency.depends_on_id",
        back_populates="depends_on",
    )
    storage_links: Mapped[list["ServiceStorage"]] = relationship(
        "ServiceStorage", back_populates="service"
    )
    misc_links: Mapped[list["ServiceMisc"]] = relationship("ServiceMisc", back_populates="service")


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    __table_args__ = (UniqueConstraint("service_id", "depends_on_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    depends_on_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship(
        "Service", foreign_keys=[service_id], back_populates="dependencies"
    )
    depends_on: Mapped["Service"] = relationship(
        "Service", foreign_keys=[depends_on_id], back_populates="dependents"
    )


# ── Storage ─────────────────────────────────────────────────────────────────


class Storage(Base):
    __tablename__ = "storage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'disk', 'pool', 'dataset', 'share'
    icon_slug: Mapped[str | None] = mapped_column(String)
    hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID))
    capacity_gb: Mapped[int | None] = mapped_column(Integer)
    used_gb: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(String)
    protocol: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    integration_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("integration_configs.id", ondelete="SET NULL"), nullable=True
    )
    proxmox_storage_name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    hardware: Mapped["Hardware | None"] = relationship("Hardware", back_populates="storage_items")
    service_links: Mapped[list["ServiceStorage"]] = relationship(
        "ServiceStorage", back_populates="storage"
    )


class ServiceStorage(Base):
    __tablename__ = "service_storage"
    __table_args__ = (UniqueConstraint("service_id", "storage_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("storage.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship("Service", back_populates="storage_links")
    storage: Mapped["Storage"] = relationship("Storage", back_populates="service_links")


# ── Misc ─────────────────────────────────────────────────────────────────────


class MiscItem(Base):
    __tablename__ = "misc_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String)
    icon_slug: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    service_links: Mapped[list["ServiceMisc"]] = relationship(
        "ServiceMisc", back_populates="misc_item"
    )


class ServiceMisc(Base):
    __tablename__ = "service_misc"
    __table_args__ = (UniqueConstraint("service_id", "misc_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    misc_id: Mapped[int] = mapped_column(Integer, ForeignKey("misc_items.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship("Service", back_populates="misc_links")
    misc_item: Mapped["MiscItem"] = relationship("MiscItem", back_populates="service_links")
