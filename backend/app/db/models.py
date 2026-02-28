from datetime import datetime, timezone
from sqlalchemy import Boolean, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


_FK_HARDWARE_ID = "hardware.id"
_FK_SERVICES_ID = "services.id"


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
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    vendor_icon_slug: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    cpu: Mapped[str | None] = mapped_column(String)
    memory_gb: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String)
    wan_uplink: Mapped[str | None] = mapped_column(String)
    cpu_brand: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    compute_units: Mapped[list["ComputeUnit"]] = relationship("ComputeUnit", back_populates="hardware")
    storage_items: Mapped[list["Storage"]] = relationship("Storage", back_populates="hardware")
    network_memberships: Mapped[list["HardwareNetwork"]] = relationship(
        "HardwareNetwork", back_populates="hardware"
    )


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
    hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True)
    icon_slug: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    ports: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)  # running | stopped | degraded | maintenance
    ip_address: Mapped[str | None] = mapped_column(String)
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
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    depends_on_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    hardware: Mapped["Hardware | None"] = relationship("Hardware", back_populates="storage_items")
    service_links: Mapped[list["ServiceStorage"]] = relationship("ServiceStorage", back_populates="storage")


class ServiceStorage(Base):
    __tablename__ = "service_storage"
    __table_args__ = (UniqueConstraint("service_id", "storage_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    storage_id: Mapped[int] = mapped_column(Integer, ForeignKey("storage.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)

    service: Mapped["Service"] = relationship("Service", back_populates="storage_links")
    storage: Mapped["Storage"] = relationship("Storage", back_populates="service_links")


# ── Networks ────────────────────────────────────────────────────────────────


class Network(Base):
    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    icon_slug: Mapped[str | None] = mapped_column(String)
    cidr: Mapped[str | None] = mapped_column(String)
    vlan_id: Mapped[int | None] = mapped_column(Integer)
    gateway: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    gateway_hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("hardware.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    gateway_hardware: Mapped["Hardware | None"] = relationship(
        "Hardware", foreign_keys=[gateway_hardware_id]
    )
    compute_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="network"
    )
    hardware_memberships: Mapped[list["HardwareNetwork"]] = relationship(
        "HardwareNetwork", back_populates="network"
    )


class HardwareNetwork(Base):
    __tablename__ = "hardware_networks"
    __table_args__ = (UniqueConstraint("hardware_id", "network_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey("hardware.id"), nullable=False)
    network_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="network_memberships")
    network: Mapped["Network"] = relationship("Network", back_populates="hardware_memberships")


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
    icon_slug: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    service_links: Mapped[list["ServiceMisc"]] = relationship("ServiceMisc", back_populates="misc_item")


class ServiceMisc(Base):
    __tablename__ = "service_misc"
    __table_args__ = (UniqueConstraint("service_id", "misc_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_SERVICES_ID), nullable=False)
    misc_id: Mapped[int] = mapped_column(Integer, ForeignKey("misc_items.id"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)

    service: Mapped["Service"] = relationship("Service", back_populates="misc_links")
    misc_item: Mapped["MiscItem"] = relationship("MiscItem", back_populates="service_links")


# ── Graph Layouts ─────────────────────────────────────────────────────────────


class GraphLayout(Base):
    __tablename__ = "graph_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # e.g. "default", "user-1-custom"
    context: Mapped[str | None] = mapped_column(String)  # e.g. "topology"
    layout_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON string
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ── App Settings ──────────────────────────────────────────────────────────────


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    theme: Mapped[str] = mapped_column(String, nullable=False, default="dark")
    default_environment: Mapped[str | None] = mapped_column(String)
    show_experimental_features: Mapped[bool] = mapped_column(
        Integer, nullable=False, default=False
    )
    api_base_url: Mapped[str | None] = mapped_column(String)
    map_default_filters: Mapped[str | None] = mapped_column(Text)  # JSON string
    vendor_icon_mode: Mapped[str] = mapped_column(String, nullable=False, default="custom_files")
    environments: Mapped[str | None] = mapped_column(Text, default='["prod","staging","dev"]')  # JSON array
    categories: Mapped[str | None] = mapped_column(Text, default='[]')  # JSON array
    locations: Mapped[str | None] = mapped_column(Text, default='[]')  # JSON array
    dock_order: Mapped[str | None] = mapped_column(Text)  # JSON array of path strings
    dock_hidden_items: Mapped[str | None] = mapped_column(Text)  # JSON array of hidden path strings
    show_page_hints: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    auth_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jwt_secret: Mapped[str | None] = mapped_column(Text)
    session_timeout_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    # Branding
    app_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    favicon_path: Mapped[str | None] = mapped_column(Text)
    login_logo_path: Mapped[str | None] = mapped_column(Text)
    primary_color: Mapped[str] = mapped_column(String, nullable=False, default="#00d4ff")
    accent_colors: Mapped[str | None] = mapped_column(Text, default='["#ff6b6b","#4ecdc4"]')  # JSON array
    # Advanced Theming
    theme_preset: Mapped[str] = mapped_column(String, nullable=False, default="cyberpunk-neon")
    custom_colors: Mapped[str | None] = mapped_column(Text)  # JSON: {primary,secondary,accent1,accent2,background,surface}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ── Users ─────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    gravatar_hash: Mapped[str | None] = mapped_column(Text)
    profile_photo: Mapped[str | None] = mapped_column(Text)  # relative path to uploaded file
    display_name: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_login: Mapped[str | None] = mapped_column(Text)


# ── Audit Logs ────────────────────────────────────────────────────────────────


class Log(Base):
    __tablename__ = "logs"

    id:          Mapped[int]          = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp:   Mapped[datetime]     = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level:       Mapped[str]          = mapped_column(String, nullable=False, default="info")
    category:    Mapped[str]          = mapped_column(String, nullable=False)   # crud | settings | relationships | docs
    action:      Mapped[str]          = mapped_column(String, nullable=False)   # create_hardware, update_service, …
    actor:       Mapped[str | None]   = mapped_column(String, default="user")
    entity_type: Mapped[str | None]   = mapped_column(String)
    entity_id:   Mapped[int | None]   = mapped_column(Integer)
    old_value:   Mapped[str | None]   = mapped_column(Text)
    new_value:   Mapped[str | None]   = mapped_column(Text)
    user_agent:  Mapped[str | None]   = mapped_column(String)
    ip_address:  Mapped[str | None]   = mapped_column(String)
    details:     Mapped[str | None]   = mapped_column(Text)
    status_code: Mapped[int | None]   = mapped_column(Integer)   # HTTP response status (added for error tracking)
