from datetime import datetime, timezone
from sqlalchemy import Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Common ─────────────────────────────────────────────────────────────────


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class Doc(Base):
    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class EntityTag(Base):
    __tablename__ = "entity_tags"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "tag_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id"), nullable=False)

    tag: Mapped["Tag"] = relationship("Tag")


class EntityDoc(Base):
    __tablename__ = "entity_docs"
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "doc_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_id: Mapped[int] = mapped_column(Integer, ForeignKey("docs.id"), nullable=False)

    doc: Mapped["Doc"] = relationship("Doc")


# ── Hardware ────────────────────────────────────────────────────────────────


class Hardware(Base):
    __tablename__ = "hardware"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String)
    vendor: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    cpu: Mapped[str | None] = mapped_column(String)
    memory_gb: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    compute_units: Mapped[list["ComputeUnit"]] = relationship("ComputeUnit", back_populates="hardware")
    storage_items: Mapped[list["Storage"]] = relationship("Storage", back_populates="hardware")


# ── Compute Units ───────────────────────────────────────────────────────────


class ComputeUnit(Base):
    __tablename__ = "compute_units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # 'vm' | 'container'
    hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey("hardware.id"), nullable=False)
    os: Mapped[str | None] = mapped_column(String)
    icon_slug: Mapped[str | None] = mapped_column(String)
    cpu_cores: Mapped[int | None] = mapped_column(Integer, name="CPU_cores")
    memory_mb: Mapped[int | None] = mapped_column(Integer)
    disk_gb: Mapped[int | None] = mapped_column(Integer)
    ip_address: Mapped[str | None] = mapped_column(String)
    environment: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="compute_units")
    services: Mapped[list["Service"]] = relationship("Service", back_populates="compute_unit")
    network_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="compute_unit"
    )


# ── Services ────────────────────────────────────────────────────────────────


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    compute_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("compute_units.id"), nullable=True)
    hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hardware.id"), nullable=True)
    category: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    ports: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    compute_unit: Mapped["ComputeUnit | None"] = relationship("ComputeUnit", back_populates="services")
    hardware: Mapped["Hardware | None"] = relationship("Hardware")
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
    storage_links: Mapped[list["ServiceStorage"]] = relationship("ServiceStorage", back_populates="service")
    misc_links: Mapped[list["ServiceMisc"]] = relationship("ServiceMisc", back_populates="service")


class ServiceDependency(Base):
    __tablename__ = "service_dependencies"
    __table_args__ = (UniqueConstraint("service_id", "depends_on_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), nullable=False)
    depends_on_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), nullable=False)

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
    hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hardware.id"))
    capacity_gb: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str | None] = mapped_column(String)
    protocol: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    hardware: Mapped["Hardware | None"] = relationship("Hardware", back_populates="storage_items")
    service_links: Mapped[list["ServiceStorage"]] = relationship("ServiceStorage", back_populates="storage")


class ServiceStorage(Base):
    __tablename__ = "service_storage"
    __table_args__ = (UniqueConstraint("service_id", "storage_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), nullable=False)
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("storage.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)

    service: Mapped["Service"] = relationship("Service", back_populates="storage_links")
    storage: Mapped["Storage"] = relationship("Storage", back_populates="service_links")


# ── Networks ────────────────────────────────────────────────────────────────


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cidr: Mapped[str | None] = mapped_column(String)
    vlan_id: Mapped[int | None] = mapped_column(Integer)
    gateway: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    compute_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="network"
    )


class ComputeNetwork(Base):
    __tablename__ = "compute_networks"
    __table_args__ = (UniqueConstraint("compute_id", "network_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    compute_id: Mapped[int] = mapped_column(Integer, ForeignKey("compute_units.id"), nullable=False)
    network_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String)

    compute_unit: Mapped["ComputeUnit"] = relationship("ComputeUnit", back_populates="network_memberships")
    network: Mapped["Network"] = relationship("Network", back_populates="compute_memberships")


# ── Misc ─────────────────────────────────────────────────────────────────────


class MiscItem(Base):
    __tablename__ = "misc_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    service_links: Mapped[list["ServiceMisc"]] = relationship("ServiceMisc", back_populates="misc_item")


class ServiceMisc(Base):
    __tablename__ = "service_misc"
    __table_args__ = (UniqueConstraint("service_id", "misc_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id"), nullable=False)
    misc_id: Mapped[int] = mapped_column(Integer, ForeignKey("misc_items.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)

    service: Mapped["Service"] = relationship("Service", back_populates="misc_links")
    misc_item: Mapped["MiscItem"] = relationship("MiscItem", back_populates="service_links")
