from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utcnow
from app.db.session import Base


def _now() -> datetime:
    return utcnow()


_FK_HARDWARE_ID = "hardware.id"
_FK_SERVICES_ID = "services.id"
_FK_RACKS_ID = "racks.id"


# ── Common ─────────────────────────────────────────────────────────────────


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)


class Doc(Base):
    __tablename__ = "docs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    # v0.1.2: sidebar organisation & per-doc identity
    category: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    icon: Mapped[str] = mapped_column(String, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


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


# ── Racks ──────────────────────────────────────────────────────────────────


class Rack(Base):
    __tablename__ = "racks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    height_u: Mapped[int] = mapped_column(Integer, nullable=False, default=42)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    hardware: Mapped[list["Hardware"]] = relationship("Hardware", back_populates="rack")


# ── Hardware ────────────────────────────────────────────────────────────────


class Hardware(Base):
    __tablename__ = "hardware"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String)
    vendor: Mapped[str | None] = mapped_column(String)
    vendor_icon_slug: Mapped[str | None] = mapped_column(String)
    custom_icon: Mapped[str | None] = mapped_column(String)
    model: Mapped[str | None] = mapped_column(String)
    cpu: Mapped[str | None] = mapped_column(String)
    memory_gb: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String)
    wan_uplink: Mapped[str | None] = mapped_column(String)
    cpu_brand: Mapped[str | None] = mapped_column(String)
    # v0.1.2: catalog linkage
    vendor_catalog_key: Mapped[str | None] = mapped_column(String)
    model_catalog_key: Mapped[str | None] = mapped_column(String)
    # v0.1.2: rack positioning
    u_height: Mapped[int | None] = mapped_column(Integer)
    rack_unit: Mapped[int | None] = mapped_column(Integer)
    # v0.1.2: telemetry (JSONB as of v0.2.0)
    telemetry_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_status: Mapped[str | None] = mapped_column(String, default="unknown")
    telemetry_last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("environments.id"), nullable=True
    )
    # v0.1.4-cortex: rack assignment + discovery lineage
    rack_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_RACKS_ID), nullable=True)
    # v2.0: rack mounting orientation (horizontal = standard U-slot, vertical = side rail)
    mounting_orientation: Mapped[str | None] = mapped_column(
        String, nullable=True, default="horizontal"
    )
    side_rail: Mapped[str | None] = mapped_column(String, nullable=True)
    source_scan_result_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scan_results.id"), nullable=True
    )
    # v0.1.4: auto-discovery
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True, default="unknown")
    status_override: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    discovered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True, default="manual")
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # v0.1.7: Networking (Router/AP) hardware extensions — JSONB as of v0.2.0
    wifi_standards: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    wifi_bands: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    max_tx_power_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_map_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    software_platform: Mapped[str | None] = mapped_column(String, nullable=True)
    download_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # v0.2.0: Proxmox integration
    proxmox_node_name: Mapped[str | None] = mapped_column(String, nullable=True)
    integration_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("integration_configs.id", ondelete="SET NULL"), nullable=True
    )
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    rack: Mapped["Rack | None"] = relationship(
        "Rack", back_populates="hardware", foreign_keys=[rack_id]
    )
    compute_units: Mapped[list["ComputeUnit"]] = relationship(
        "ComputeUnit", back_populates="hardware"
    )
    environment_rel: Mapped["Environment | None"] = relationship(
        "Environment", back_populates="hardware", foreign_keys=[environment_id]
    )
    storage_items: Mapped[list["Storage"]] = relationship("Storage", back_populates="hardware")
    capacity_forecasts: Mapped[list["CapacityForecast"]] = relationship(
        "CapacityForecast", back_populates="hardware", cascade="all, delete-orphan"
    )
    network_memberships: Mapped[list["HardwareNetwork"]] = relationship(
        "HardwareNetwork", back_populates="hardware"
    )
    cluster_memberships: Mapped[list["HardwareClusterMember"]] = relationship(
        "HardwareClusterMember", back_populates="hardware"
    )
    outgoing_connections: Mapped[list["HardwareConnection"]] = relationship(
        "HardwareConnection",
        foreign_keys="HardwareConnection.source_hardware_id",
        back_populates="source_hardware",
    )
    incoming_connections: Mapped[list["HardwareConnection"]] = relationship(
        "HardwareConnection",
        foreign_keys="HardwareConnection.target_hardware_id",
        back_populates="target_hardware",
    )
    monitor: Mapped["HardwareMonitor | None"] = relationship(
        "HardwareMonitor", back_populates="hardware", uselist=False
    )
    integration_monitors: Mapped[list["IntegrationMonitor"]] = relationship(
        "IntegrationMonitor",
        foreign_keys="IntegrationMonitor.linked_hardware_id",
        back_populates="linked_hardware",
    )


# ── Uptime Monitoring ────────────────────────────────────────────────────────


class HardwareMonitor(Base):
    """One monitoring config row per hardware device."""

    __tablename__ = "hardware_monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), unique=True, nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_secs: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    # JSON array: ["icmp","tcp","http","snmp"] — JSONB as of v0.2.0
    probe_methods: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=lambda: ["icmp", "tcp", "http"]
    )
    last_status: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    last_checked_at: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_pct_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="monitor")


class UptimeEvent(Base):
    """Rolling history of probe results for a monitored hardware device."""

    __tablename__ = "uptime_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)  # "up" | "down"
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    probe_method: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[str] = mapped_column(String, nullable=False)

    hardware: Mapped["Hardware"] = relationship("Hardware")


class DailyUptimeStats(Base):
    """Daily aggregated rollups for hardware uptime."""

    __tablename__ = "daily_uptime_stats"
    __table_args__ = (UniqueConstraint("hardware_id", "date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID, ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO date string YYYY-MM-DD
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    hardware: Mapped["Hardware"] = relationship("Hardware")


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
    ports_json: Mapped[str | None] = mapped_column(Text)
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
    gateway_hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True
    )
    # Docker network metadata
    docker_network_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    docker_driver: Mapped[str | None] = mapped_column(String, nullable=True)
    is_docker_network: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    site_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sites.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    gateway_hardware: Mapped["Hardware | None"] = relationship(
        "Hardware", foreign_keys=[gateway_hardware_id]
    )
    compute_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="network"
    )
    hardware_memberships: Mapped[list["HardwareNetwork"]] = relationship(
        "HardwareNetwork", back_populates="network"
    )
    peers_as_a: Mapped[list["NetworkPeer"]] = relationship(
        "NetworkPeer",
        foreign_keys="NetworkPeer.network_a_id",
        back_populates="network_a",
        cascade="all, delete-orphan",
    )
    peers_as_b: Mapped[list["NetworkPeer"]] = relationship(
        "NetworkPeer",
        foreign_keys="NetworkPeer.network_b_id",
        back_populates="network_b",
        cascade="all, delete-orphan",
    )
    site: Mapped["Site | None"] = relationship("Site", foreign_keys=[site_id])


class NetworkPeer(Base):
    __tablename__ = "network_peers"
    __table_args__ = (UniqueConstraint("network_a_id", "network_b_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    network_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    network_b_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    relation: Mapped[str] = mapped_column(String, nullable=False, default="peers_with")
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    network_a: Mapped["Network"] = relationship(
        "Network", foreign_keys=[network_a_id], back_populates="peers_as_a"
    )
    network_b: Mapped["Network"] = relationship(
        "Network", foreign_keys=[network_b_id], back_populates="peers_as_b"
    )


class HardwareNetwork(Base):
    __tablename__ = "hardware_networks"
    __table_args__ = (UniqueConstraint("hardware_id", "network_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False)
    network_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="network_memberships")
    network: Mapped["Network"] = relationship("Network", back_populates="hardware_memberships")


class ComputeNetwork(Base):
    __tablename__ = "compute_networks"
    __table_args__ = (UniqueConstraint("compute_id", "network_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    compute_id: Mapped[int] = mapped_column(Integer, ForeignKey("compute_units.id"), nullable=False)
    network_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id"), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    compute_unit: Mapped["ComputeUnit"] = relationship(
        "ComputeUnit", back_populates="network_memberships"
    )
    network: Mapped["Network"] = relationship("Network", back_populates="compute_memberships")


class HardwareConnection(Base):
    """Direct hardware-to-hardware physical connection (e.g. switch uplink, crossover cable)."""

    __tablename__ = "hardware_connections"
    __table_args__ = (UniqueConstraint("source_hardware_id", "target_hardware_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False
    )
    target_hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False
    )
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)
    source_port: Mapped[str | None] = mapped_column(String, nullable=True)
    target_port: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    source_hardware: Mapped["Hardware"] = relationship(
        "Hardware", foreign_keys=[source_hardware_id], back_populates="outgoing_connections"
    )
    target_hardware: Mapped["Hardware"] = relationship(
        "Hardware", foreign_keys=[target_hardware_id], back_populates="incoming_connections"
    )


# ── Hardware Clusters ────────────────────────────────────────────────────────


class HardwareCluster(Base):
    __tablename__ = "hardware_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    icon_slug: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    type: Mapped[str] = mapped_column(String, default="manual")
    # values: manual | docker_compose | docker_swarm | k8s | proxmox
    integration_config_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("integration_configs.id", ondelete="SET NULL"), nullable=True
    )
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    members: Mapped[list["HardwareClusterMember"]] = relationship(
        "HardwareClusterMember", back_populates="cluster", cascade="all, delete-orphan"
    )


class HardwareClusterMember(Base):
    __tablename__ = "hardware_cluster_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hardware_clusters.id"), nullable=False
    )
    member_type: Mapped[str] = mapped_column(String, default="hardware")
    # hardware | service
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True
    )
    service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey(_FK_SERVICES_ID, ondelete="CASCADE"), nullable=True
    )
    role: Mapped[str | None] = mapped_column(String)

    cluster: Mapped["HardwareCluster"] = relationship("HardwareCluster", back_populates="members")
    hardware: Mapped["Hardware | None"] = relationship(
        "Hardware", back_populates="cluster_memberships", foreign_keys=[hardware_id]
    )
    service: Mapped["Service | None"] = relationship("Service", foreign_keys=[service_id])


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


# ── External Nodes (Off-Prem / Cloud) ─────────────────────────────────────────


class ExternalNode(Base):
    __tablename__ = "external_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String)  # e.g. 'Hetzner', 'AWS', 'Cloudflare'
    kind: Mapped[str | None] = mapped_column(
        String
    )  # 'vps', 'managed_db', 'saas', 'vpn_gateway', etc.
    region: Mapped[str | None] = mapped_column(String)  # 'us-west-2', 'nbg1', 'global', etc.
    ip_address: Mapped[str | None] = mapped_column(String)  # primary IP or hostname
    icon_slug: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)  # 'prod', 'lab', 'shared'
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    network_links: Mapped[list["ExternalNodeNetwork"]] = relationship(
        "ExternalNodeNetwork", back_populates="external_node", cascade="all, delete-orphan"
    )
    service_links: Mapped[list["ServiceExternalNode"]] = relationship(
        "ServiceExternalNode", back_populates="external_node", cascade="all, delete-orphan"
    )


class ExternalNodeNetwork(Base):
    __tablename__ = "external_node_networks"
    __table_args__ = (UniqueConstraint("external_node_id", "network_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("external_nodes.id", ondelete="CASCADE"), nullable=False
    )
    network_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("networks.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str | None] = mapped_column(
        String
    )  # 'vpn', 'wan', 'wireguard', 'reverse_proxy', etc.
    notes: Mapped[str | None] = mapped_column(Text)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    external_node: Mapped["ExternalNode"] = relationship(
        "ExternalNode", back_populates="network_links"
    )
    network: Mapped["Network"] = relationship("Network")


class ServiceExternalNode(Base):
    __tablename__ = "service_external_nodes"
    __table_args__ = (UniqueConstraint("service_id", "external_node_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    external_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("external_nodes.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str | None] = mapped_column(
        String
    )  # 'db', 'auth', 'cache', 'upstream_api', etc.
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship("Service")
    external_node: Mapped["ExternalNode"] = relationship(
        "ExternalNode", back_populates="service_links"
    )


# ── Graph Layouts ─────────────────────────────────────────────────────────────


class GraphLayout(Base):
    __tablename__ = "graph_layouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )  # e.g. "default", "user-1-custom"
    context: Mapped[str | None] = mapped_column(String)  # e.g. "topology"
    layout_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # JSONB as of v0.2.0; deprecated — use Topology model
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    topology_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("topologies.id", ondelete="CASCADE"), nullable=True, index=True
    )


# ── App Settings ──────────────────────────────────────────────────────────────


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    theme: Mapped[str] = mapped_column(String, nullable=False, default="dark")
    default_environment: Mapped[str | None] = mapped_column(String)
    show_experimental_features: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_base_url: Mapped[str | None] = mapped_column(String)
    vendor_icon_mode: Mapped[str] = mapped_column(String, nullable=False, default="custom_files")
    environments: Mapped[str | None] = mapped_column(
        Text, default='["prod","staging","dev"]'
    )  # JSON array
    categories: Mapped[str | None] = mapped_column(Text, default="[]")  # JSON array
    locations: Mapped[str | None] = mapped_column(Text, default="[]")  # JSON array
    dock_order: Mapped[str | None] = mapped_column(Text)  # JSON array of path strings
    dock_hidden_items: Mapped[str | None] = mapped_column(Text)  # JSON array of hidden path strings
    show_page_hints: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_header_widgets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_time_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_weather_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weather_location: Mapped[str] = mapped_column(String, nullable=False, default="Phoenix, AZ")
    auth_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_profile: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    jwt_secret: Mapped[str | None] = mapped_column(Text)
    client_hash_salt: Mapped[str | None] = mapped_column(Text)
    session_timeout_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    dev_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    audit_log_hide_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    telemetry_hot_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telemetry_warm_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Branding
    app_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    favicon_path: Mapped[str | None] = mapped_column(Text)
    login_logo_path: Mapped[str | None] = mapped_column(Text)
    login_bg_path: Mapped[str | None] = mapped_column(Text)
    primary_color: Mapped[str] = mapped_column(String, nullable=False, default="#fe8019")
    accent_colors: Mapped[list | None] = mapped_column(
        JSONB, default=lambda: ["#fabd2f", "#b8bb26"]
    )  # JSONB as of v0.2.0
    # Advanced Theming
    theme_preset: Mapped[str] = mapped_column(String, nullable=False, default="gruvbox-dark")
    custom_colors: Mapped[dict | None] = mapped_column(
        JSONB
    )  # JSONB: {primary,secondary,accent1,accent2,background,surface}
    # External nodes
    show_external_nodes_on_map: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Timezone preference (IANA name, e.g. "America/Denver")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    # Auto-Discovery settings
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_auto_merge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_default_cidr: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_nmap_args: Mapped[str] = mapped_column(
        String, nullable=False, default="-sV -O --open -T4"
    )
    discovery_snmp_community: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_schedule_cron: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_http_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovery_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    scan_ack_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Safe discovery mode
    discovery_mode: Mapped[str] = mapped_column(String, nullable=False, default="safe")
    docker_discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    docker_socket_path: Mapped[str] = mapped_column(
        String, nullable=False, default="/var/run/docker.sock"
    )
    docker_sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    graph_default_layout: Mapped[str] = mapped_column(String, nullable=False, default="dagre")
    map_title: Mapped[str] = mapped_column(String, nullable=False, default="Topology")
    graph_uplink_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    map_default_filters: Mapped[dict | None] = mapped_column(JSONB)  # JSONB as of v0.2.0
    # Font preferences
    ui_font: Mapped[str] = mapped_column(String, nullable=False, default="inter")
    ui_font_size: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    # CVE sync
    cve_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cve_sync_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    cve_last_sync_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # Phase 3: Realtime / NATS settings
    realtime_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    realtime_transport: Mapped[str] = mapped_column(
        String, nullable=False, default="auto"
    )  # "auto" | "sse" | "websocket"
    # Phase 4: Discovery Engine 2.0 toggles
    listener_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prober_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    deep_dive_max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    scan_aggressiveness: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    mdns_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ssdp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Feature 8: Federated Auth — JSONB as of v0.2.0
    oauth_providers: Mapped[dict | None] = mapped_column(
        JSONB
    )  # JSONB: {"github": {...}, "google": {...}}
    oidc_providers: Mapped[list | None] = mapped_column(JSONB)  # JSONB array of OIDC providers
    arp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tcp_probe_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Mobile / phone discovery
    mobile_discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mdns_multicast_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mdns_listener_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    dhcp_lease_file_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Router SSH for DHCP snooping (opt-in, vault-encrypted)
    dhcp_router_host: Mapped[str] = mapped_column(String, nullable=False, default="")
    dhcp_router_user_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    dhcp_router_pass_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    dhcp_router_command: Mapped[str] = mapped_column(
        String, nullable=False, default="cat /var/lib/misc/dnsmasq.leases"
    )
    # v0.2.0: Self-aware cluster
    self_cluster_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 6.5: User management
    concurrent_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    login_lockout_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    login_lockout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    invite_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    masquerade_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_concurrent_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # SMTP / Email delivery
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    smtp_host: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_username: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_password_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    smtp_from_email: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_from_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    smtp_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    smtp_last_test_at: Mapped[str | None] = mapped_column(String)
    smtp_last_test_status: Mapped[str | None] = mapped_column(String)
    # Phase 7: Vault encryption
    vault_key: Mapped[str | None] = mapped_column(
        Text
    )  # Plaintext key for DB fallback when env/file unwritable
    vault_key_hash: Mapped[str | None] = mapped_column(Text)  # SHA-256 of the vault key
    vault_key_rotation_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    vault_key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phase 7.5: PostgreSQL backup retention
    db_backup_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Security hardening
    scan_allowed_networks: Mapped[str] = mapped_column(
        Text, nullable=False, default='["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]'
    )  # JSON array of allowed CIDRs for scanning
    airgap_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ws_allowed_cidrs: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )  # JSON array of CIDRs allowed to connect via WebSocket; empty = allow all
    # Backup / DR settings (migration 0057)
    backup_s3_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_access_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_secret_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_s3_region: Mapped[str] = mapped_column(String, nullable=False, default="us-east-1")
    backup_s3_prefix: Mapped[str] = mapped_column(
        String, nullable=False, default="circuitbreaker/backups/"
    )
    backup_s3_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    backup_local_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Native monitor pipeline
    auto_monitor_on_discovery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Onboarding (OOBE step state, Homarr-style) ─────────────────────────────────
# Single row (id=1). Only relevant when needs_bootstrap is True.


class Onboarding(Base):
    __tablename__ = "onboarding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    step: Mapped[str] = mapped_column(String, nullable=False, default="start")
    previous_step: Mapped[str] = mapped_column(String, nullable=False, default="start")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Credentials (encrypted per-entity secrets) ────────────────────────────────


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    credential_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # snmp|ssh|ipmi|smtp|api_key|proxmox_api
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Integration Configs ───────────────────────────────────────────────────────


class IntegrationConfig(Base):
    __tablename__ = "integration_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)  # "proxmox" (extensible)
    name: Mapped[str] = mapped_column(String, nullable=False)
    config_url: Mapped[str] = mapped_column(String, nullable=False)
    credential_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("credentials.id"), nullable=True
    )
    cluster_name: Mapped[str | None] = mapped_column(String, nullable=True)
    auto_sync: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sync_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_poll_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tls_cert_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("certificates.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    credential: Mapped["Credential | None"] = relationship(
        "Credential", foreign_keys=[credential_id]
    )
    tls_cert: Mapped["Certificate | None"] = relationship("Certificate", foreign_keys=[tls_cert_id])


class ProxmoxDiscoverRun(Base):
    """One run of Proxmox cluster discovery (nodes, VMs, CTs, storage)."""

    __tablename__ = "proxmox_discover_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, index=True)
    integration_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_configs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="running"
    )  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    nodes_imported: Mapped[int] = mapped_column(Integer, default=0)
    vms_imported: Mapped[int] = mapped_column(Integer, default=0)
    cts_imported: Mapped[int] = mapped_column(Integer, default=0)
    storage_imported: Mapped[int] = mapped_column(Integer, default=0)
    networks_imported: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # list of error strings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    integration: Mapped["IntegrationConfig"] = relationship(
        "IntegrationConfig", foreign_keys=[integration_id]
    )


# ── Auto Discovery ────────────────────────────────────────────────────────────


class DiscoveryProfile(Base):
    __tablename__ = "discovery_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cidr: Mapped[str | None] = mapped_column(String, nullable=True)
    vlan_ids: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON array of VLAN IDs
    scan_types: Mapped[str] = mapped_column(String, default='["nmap"]')
    nmap_arguments: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_community_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_version: Mapped[str] = mapped_column(String, default="2c")
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    docker_network_types: Mapped[str] = mapped_column(String, default='["bridge"]')
    docker_port_scan: Mapped[int] = mapped_column(Integer, default=0)
    docker_socket_path: Mapped[str] = mapped_column(String, default="/var/run/docker.sock")
    schedule_cron: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    jobs: Mapped[list["ScanJob"]] = relationship("ScanJob", back_populates="profile")


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("discovery_profiles.id"), nullable=True
    )
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    target_cidr: Mapped[str | None] = mapped_column(String, nullable=True)
    vlan_ids: Mapped[str | None] = mapped_column(String, nullable=True)  # JSON array of VLAN IDs
    network_ids: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # JSON array of network IDs
    scan_types_json: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    hosts_found: Mapped[int] = mapped_column(Integer, default=0)
    hosts_new: Mapped[int] = mapped_column(Integer, default=0)
    hosts_updated: Mapped[int] = mapped_column(Integer, default=0)
    hosts_conflict: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, default="api")
    source_type: Mapped[str] = mapped_column(
        String, default="manual"
    )  # manual|prober|scheduled|listener_triggered
    progress_phase: Mapped[str] = mapped_column(String, default="queued")
    progress_message: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # v0.2.0: multi-tenancy (renamed from team_id in v0.3.0)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True
    )

    profile: Mapped["DiscoveryProfile | None"] = relationship(
        "DiscoveryProfile", back_populates="jobs"
    )
    results: Mapped[list["ScanResult"]] = relationship("ScanResult", back_populates="job")
    logs: Mapped[list["ScanLog"]] = relationship("ScanLog", back_populates="job")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scan_jobs.id"), nullable=False, index=True
    )
    ip_address: Mapped[str] = mapped_column(String, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    open_ports_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    os_family: Mapped[str | None] = mapped_column(String, nullable=True)
    os_vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_name: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_descr: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_interfaces_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # JSONB as of v0.2.0
    snmp_storage_json: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )  # JSONB as of v0.2.0
    lldp_neighbors_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    network_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("networks.id"), nullable=True
    )
    raw_nmap_xml: Mapped[str | None] = mapped_column(String, nullable=True)
    banner: Mapped[str | None] = mapped_column(Text, nullable=True)  # service banner from TCP probe
    os_accuracy: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # 0–100 nmap OS confidence
    device_type: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # ios_device|android_device|fire_tv|router|printer|nas|smart_tv|ip_camera|windows_pc|…
    device_confidence: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )  # 0–100 classification confidence
    source_type: Mapped[str] = mapped_column(
        String, default="nmap"
    )  # nmap|arp|listener|prober|deep_dive|docker
    state: Mapped[str] = mapped_column(String, default="new", index=True)
    conflicts_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    matched_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merge_status: Mapped[str] = mapped_column(String, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False, index=True)

    job: Mapped["ScanJob"] = relationship("ScanJob", back_populates="results")


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_jobs.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False)  # INFO, SUCCESS, WARN, ERROR
    phase: Mapped[str | None] = mapped_column(String, nullable=True)  # ping, arp, nmap, snmp, http
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Raw command output, error traces
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    job: Mapped["ScanJob"] = relationship("ScanJob", back_populates="logs")


# ── Phase 4: Listener Events ──────────────────────────────────────────────────


class ListenerEvent(Base):
    """mDNS / SSDP advertisements captured by the always-on listener."""

    __tablename__ = "listener_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "mdns" | "ssdp"
    service_type: Mapped[str | None] = mapped_column(String, nullable=True)  # "_http._tcp.local."
    name: Mapped[str | None] = mapped_column(String, nullable=True)  # advertised service name
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    properties_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )  # TXT records / SSDP headers — JSONB as of v0.2.0
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


# ── Users ─────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    gravatar_hash: Mapped[str | None] = mapped_column(Text)
    profile_photo: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_login: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), onupdate=_now)
    # Phase 6.5: RBAC, invite, lockout, masquerade
    role: Mapped[str] = mapped_column(String, nullable=False, default="viewer")
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    demo_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    masquerade_target: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    # Local user creation: force a password change on first login
    force_password_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # External Auth
    provider: Mapped[str] = mapped_column(
        String, nullable=False, default="local"
    )  # "local", "github", "oidc"
    oauth_tokens: Mapped[str | None] = mapped_column(Text)  # JSON blob for oauth refresh tokens etc
    # MFA / TOTP (Phase 7 security hardening)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_codes: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON list of hashed codes
    # v0.3.0: tenant assignment
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )

    sessions: Mapped[list["UserSession"]] = relationship(
        "UserSession",
        back_populates="user",
        foreign_keys="UserSession.user_id",
        passive_deletes=True,
    )


# ── Phase 6.5: User Sessions & Invites ────────────────────────────────────────


class UserSession(Base):
    """Server-side session tracking for JWT revocation."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    jwt_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="sessions")


class UserInvite(Base):
    """Invite tokens for onboarding new users with a specific role."""

    __tablename__ = "user_invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    invited_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Email delivery tracking
    email_sent_at: Mapped[str | None] = mapped_column(String)
    email_status: Mapped[str] = mapped_column(String, nullable=False, default="not_sent")
    email_error: Mapped[str | None] = mapped_column(Text)


# ── API Tokens (machine–machine, server-generated, never stored plaintext) ────


class APIToken(Base):
    """Long-lived Bearer tokens for scripts/CI. Only token_hash is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scopes: Mapped[list | None] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ── Audit Logs ────────────────────────────────────────────────────────────────


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    level: Mapped[str] = mapped_column(String, nullable=False, default="info")
    category: Mapped[str] = mapped_column(
        String, nullable=False
    )  # crud | settings | relationships | docs
    action: Mapped[str] = mapped_column(
        String, nullable=False
    )  # create_hardware, update_service, …
    actor: Mapped[str | None] = mapped_column(String, default="anonymous")
    actor_gravatar_hash: Mapped[str | None] = mapped_column(String)
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(String)
    ip_address: Mapped[str | None] = mapped_column(String)
    details: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(
        Integer
    )  # HTTP response status (added for error tracking)
    created_at_utc: Mapped[str | None] = mapped_column(
        String
    )  # ISO 8601 UTC string; canonical timestamp for frontend display
    # Feature 6: structured audit fields
    actor_id: Mapped[int | None] = mapped_column(Integer)
    actor_name: Mapped[str | None] = mapped_column(String, default="system")
    entity_name: Mapped[str | None] = mapped_column(String)  # denormalised name at write time
    diff: Mapped[str | None] = mapped_column(Text)  # JSON: {"before": {...}, "after": {...}}
    severity: Mapped[str | None] = mapped_column(String, default="info")  # info | warn | error
    # Phase 6.5: session and role context
    session_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("user_sessions.id"), nullable=True
    )
    role_at_time: Mapped[str | None] = mapped_column(String, nullable=True)

    # Phase 7: Non-repudiation
    previous_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    log_hash: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)


class UserIcon(Base):
    __tablename__ = "user_icons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filename: Mapped[str | None] = mapped_column(String)
    original_name: Mapped[str | None] = mapped_column(String)
    mime_type: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    hash: Mapped[str | None] = mapped_column(String, unique=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Live Metrics ────────────────────────────────────────────────────────────


class LiveMetric(Base):
    __tablename__ = "live_metrics"

    ip: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str | None] = mapped_column(String)  # e.g., hw-123
    node_type: Mapped[str | None] = mapped_column(String)  # hardware/service
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(String)  # up/down/offline
    assigned_to: Mapped[str | None] = mapped_column(String)  # service slug or null
    subnet: Mapped[str | None] = mapped_column(String)  # 10.10.10.0/24


# ── Hardware Live Metrics ───────────────────────────────────────────────────


class HardwareLiveMetric(Base):
    __tablename__ = "hardware_live_metrics"
    # TimescaleDB requires the partitioning (time) column to be part of the PK.
    __table_args__ = (PrimaryKeyConstraint("id", "collected_at"),)

    id: Mapped[int] = mapped_column(BigInteger, autoincrement=True, nullable=False)
    hardware_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="CASCADE"), nullable=False, index=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_used_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_total_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    temp_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_s: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Telemetry Timeseries ─────────────────────────────────────────────────────


class TelemetryTimeseries(Base):
    __tablename__ = "telemetry_timeseries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)  # 'hardware' | 'compute_unit'
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)  # 'cpu_pct', 'mem_used_gb', etc.
    value: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True, default="proxmox")
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=_now)


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


# ── Webhooks & Notifications ──────────────────────────────────────────────────


class WebhookRule(Base):
    __tablename__ = "webhook_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)  # display label
    target_url: Mapped[str] = mapped_column(String, nullable=False)
    secret: Mapped[str | None] = mapped_column(String, nullable=True)  # Used for HMAC signing
    # Backward-compat field; superseded by events_enabled for v1 webhook UI.
    topics: Mapped[str] = mapped_column(String, nullable=False, default="*")
    events_enabled: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list
    )  # JSONB as of v0.2.0
    headers_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    body_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class NotificationSink(Base):
    __tablename__ = "notification_sinks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    provider_type: Mapped[str] = mapped_column(String, nullable=False)  # 'slack', 'email', 'teams'
    provider_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # JSONB (encrypted if needed) — v0.2.0
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


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("webhook_rules.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[str] = mapped_column(String, nullable=False)
    is_dlq: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dlq_at: Mapped[str | None] = mapped_column(String, nullable=True)
    replayed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    invite_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    nonce: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Status Page ──────────────────────────────────────────────────────────────


class StatusPage(Base):
    __tablename__ = "status_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    integration_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    groups: Mapped[list["StatusGroup"]] = relationship(
        "StatusGroup", back_populates="status_page", cascade="all, delete-orphan"
    )


class StatusGroup(Base):
    __tablename__ = "status_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status_page_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("status_pages.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    nodes: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    services: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    status_page: Mapped["StatusPage"] = relationship("StatusPage", back_populates="groups")
    history: Mapped[list["StatusHistory"]] = relationship(
        "StatusHistory", back_populates="group", cascade="all, delete-orphan"
    )


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("status_groups.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    overall_status: Mapped[str] = mapped_column(String, nullable=False)  # up/down/degraded/unknown
    uptime_pct: Mapped[float] = mapped_column(Float, nullable=False)
    avg_ping: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0
    raw_telemetry: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # JSONB as of v0.2.0

    group: Mapped["StatusGroup"] = relationship("StatusGroup", back_populates="history")


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


# ── Explicit Topologies ────────────────────────────────────────────────────────


class Topology(Base):
    __tablename__ = "topologies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    nodes: Mapped[list["TopologyNode"]] = relationship(
        "TopologyNode", cascade="all, delete-orphan", back_populates="topology"
    )
    edges: Mapped[list["TopologyEdge"]] = relationship(
        "TopologyEdge", cascade="all, delete-orphan", back_populates="topology"
    )


class TopologyNode(Base):
    __tablename__ = "topology_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topology_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # hardware|service|network|external_node
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[float | None] = mapped_column(Float, nullable=True)
    y: Mapped[float | None] = mapped_column(Float, nullable=True)
    size: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # freeform positioning data

    topology: Mapped["Topology"] = relationship("Topology", back_populates="nodes")


class TopologyEdge(Base):
    __tablename__ = "topology_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topology_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topologies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topology_nodes.id", ondelete="CASCADE"), nullable=False
    )
    edge_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="ethernet"
    )  # ethernet|vpn|fiber|wifi|…
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    topology: Mapped["Topology"] = relationship("Topology", back_populates="edges")


class MapPinnedEntity(Base):
    """Entities that appear on every map regardless of topology_nodes membership."""

    __tablename__ = "map_pinned_entities"

    entity_type: Mapped[str] = mapped_column(String(50), primary_key=True, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)


# ── Certificates ──────────────────────────────────────────────────────────────


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="selfsigned"
    )  # letsencrypt | selfsigned
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Audit Log (DB-trigger populated, read-only from Python) ──────────────────


class AuditLog(Base):
    """Partitioned audit table populated by DB triggers -- read-only from Python."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, primary_key=True
    )


# ── IPAM (IP Address Management) ─────────────────────────────────────────────


class IPAddress(Base):
    __tablename__ = "ip_addresses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "address", name="uq_ip_addresses_tenant_address"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    network_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("networks.id", ondelete="CASCADE"), nullable=True
    )
    address = mapped_column(INET, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free"
    )  # allocated | reserved | free
    hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="SET NULL"), nullable=True
    )
    service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allocated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    network: Mapped["Network | None"] = relationship("Network", foreign_keys=[network_id])
    hardware: Mapped["Hardware | None"] = relationship("Hardware", foreign_keys=[hardware_id])
    service: Mapped["Service | None"] = relationship("Service", foreign_keys=[service_id])


# ── VLANs (Layer 2) ──────────────────────────────────────────────────────────


class VLAN(Base):
    __tablename__ = "vlans"
    __table_args__ = (UniqueConstraint("tenant_id", "vlan_id", name="uq_vlans_tenant_vlan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    vlan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    network_ids: Mapped[list | None] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Sites (Multi-Site) ───────────────────────────────────────────────────────


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# ── Node Relations (Generic Graph Edges) ──────────────────────────────────────


class NodeRelation(Base):
    __tablename__ = "node_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_node_rel_edge",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


# ── Integrations ─────────────────────────────────────────────────────────────


class Integration(Base):
    __tablename__ = "integrations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    # integration-specific slug (e.g. status page slug)
    slug: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sync_interval_s: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(16), default="never")  # "ok"|"error"|"never"
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    monitors: Mapped[list["IntegrationMonitor"]] = relationship(
        "IntegrationMonitor", back_populates="integration", cascade="all, delete-orphan"
    )


class IntegrationMonitor(Base):
    __tablename__ = "integration_monitors"
    __table_args__ = (UniqueConstraint("integration_id", "external_id", name="uq_intmon_ext_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    integration_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # "up"|"down"|"pending"|"maintenance"
    status: Mapped[str] = mapped_column(String(16), default="pending")
    uptime_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_30d: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    avg_response_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cert_expiry_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_hardware_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("hardware.id", ondelete="SET NULL"), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Native probe configuration (NULL for Uptime Kuma monitors)
    linked_service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    probe_type: Mapped[str | None] = mapped_column(String, nullable=True)  # icmp | http | tcp
    probe_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    probe_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probe_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    integration: Mapped["Integration"] = relationship("Integration", back_populates="monitors")
    events: Mapped[list["IntegrationMonitorEvent"]] = relationship(
        "IntegrationMonitorEvent", back_populates="monitor", cascade="all, delete-orphan"
    )
    linked_hardware: Mapped["Hardware | None"] = relationship(
        "Hardware", foreign_keys=[linked_hardware_id], back_populates="integration_monitors"
    )
    linked_service: Mapped["Service | None"] = relationship(
        "Service", foreign_keys=[linked_service_id]
    )


class IntegrationMonitorEvent(Base):
    __tablename__ = "integration_monitor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("integration_monitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str] = mapped_column(String(16), nullable=False)
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Admin annotation — reason for this state change
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    monitor: Mapped["IntegrationMonitor"] = relationship(
        "IntegrationMonitor", back_populates="events"
    )


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
