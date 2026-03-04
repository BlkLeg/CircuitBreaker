from datetime import datetime
from sqlalchemy import Boolean, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column

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


# ── Racks ──────────────────────────────────────────────────────────────────


class Rack(Base):
    __tablename__ = "racks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    height_u: Mapped[int] = mapped_column(Integer, nullable=False, default=42)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    hardware: Mapped[list["Hardware"]] = relationship("Hardware", back_populates="rack")


# ── Hardware ────────────────────────────────────────────────────────────────


class Hardware(Base):
    __tablename__ = "hardware"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
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
    # v0.1.2: telemetry (JSON stored as Text for SQLite compatibility)
    telemetry_config: Mapped[str | None] = mapped_column(Text)
    telemetry_data: Mapped[str | None] = mapped_column(Text)
    telemetry_status: Mapped[str | None] = mapped_column(String, default="unknown")
    telemetry_last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("environments.id"), nullable=True)
    # v0.1.4-cortex: rack assignment + discovery lineage
    rack_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_RACKS_ID), nullable=True)
    source_scan_result_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scan_results.id"), nullable=True)
    # v0.1.4: auto-discovery
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True, default="unknown")
    status_override: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    last_seen: Mapped[str | None] = mapped_column(String, nullable=True)
    discovered_at: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True, default="manual")
    os_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # v0.1.7: Networking (Router/AP) hardware extensions
    wifi_standards: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    wifi_bands: Mapped[str | None] = mapped_column(Text, nullable=True)      # JSON array
    max_tx_power_dbm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    port_map_json: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON array
    software_platform: Mapped[str | None] = mapped_column(String, nullable=True)
    download_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    rack: Mapped["Rack | None"] = relationship("Rack", back_populates="hardware", foreign_keys=[rack_id])
    compute_units: Mapped[list["ComputeUnit"]] = relationship("ComputeUnit", back_populates="hardware")
    environment_rel: Mapped["Environment | None"] = relationship("Environment", back_populates="hardware", foreign_keys=[environment_id])
    storage_items: Mapped[list["Storage"]] = relationship("Storage", back_populates="hardware")
    network_memberships: Mapped[list["HardwareNetwork"]] = relationship(
        "HardwareNetwork", back_populates="hardware"
    )
    cluster_memberships: Mapped[list["HardwareClusterMember"]] = relationship(
        "HardwareClusterMember", back_populates="hardware"
    )
    outgoing_connections: Mapped[list["HardwareConnection"]] = relationship(
        "HardwareConnection", foreign_keys="HardwareConnection.source_hardware_id", back_populates="source_hardware"
    )
    incoming_connections: Mapped[list["HardwareConnection"]] = relationship(
        "HardwareConnection", foreign_keys="HardwareConnection.target_hardware_id", back_populates="target_hardware"
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
    download_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    environment: Mapped[str | None] = mapped_column(String)
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("environments.id"), nullable=True)
    # v0.1.4-cortex: derived status from child services
    status: Mapped[str | None] = mapped_column(String, nullable=True, default="unknown")
    status_override: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="compute_units")
    environment_rel: Mapped["Environment | None"] = relationship("Environment", back_populates="compute_units", foreign_keys=[environment_id])
    services: Mapped[list["Service"]] = relationship("Service", back_populates="compute_unit")
    network_memberships: Mapped[list["ComputeNetwork"]] = relationship(
        "ComputeNetwork", back_populates="compute_unit"
    )


# ── Categories ──────────────────────────────────────────────────────────────


class Category(Base):
    __tablename__ = "categories"

    id:         Mapped[int]      = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str]      = mapped_column(String, nullable=False, unique=True)
    color:      Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str]      = mapped_column(String, nullable=False)

    services: Mapped[list["Service"]] = relationship("Service", back_populates="category_rel")


# ── Environments ─────────────────────────────────────────────────────────────


class Environment(Base):
    __tablename__ = "environments"

    id:         Mapped[int]        = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:       Mapped[str]        = mapped_column(String, nullable=False, unique=True)
    color:      Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str]        = mapped_column(String, nullable=False)

    hardware:      Mapped[list["Hardware"]]    = relationship("Hardware",    back_populates="environment_rel")
    compute_units: Mapped[list["ComputeUnit"]] = relationship("ComputeUnit", back_populates="environment_rel")
    services:      Mapped[list["Service"]]     = relationship("Service",     back_populates="environment_rel")


# ── Services ────────────────────────────────────────────────────────────────


class Service(Base):
    __tablename__ = "services"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    compute_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("compute_units.id"), nullable=True)
    hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True)
    icon_slug: Mapped[str | None] = mapped_column(String)
    custom_icon: Mapped[str | None] = mapped_column(String)
    category: Mapped[str | None] = mapped_column(String)
    category_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("categories.id"), nullable=True)
    url: Mapped[str | None] = mapped_column(String)
    ports: Mapped[str | None] = mapped_column(String)
    ports_json: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("environments.id"), nullable=True)
    status: Mapped[str | None] = mapped_column(String)  # running | stopped | degraded | maintenance
    ip_address: Mapped[str | None] = mapped_column(String)
    # IP conflict classification (host-chain-aware)
    ip_mode: Mapped[str] = mapped_column(Text, default="explicit", server_default="explicit")
    ip_conflict: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    ip_conflict_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    compute_unit: Mapped["ComputeUnit | None"] = relationship("ComputeUnit", back_populates="services")
    hardware: Mapped["Hardware | None"] = relationship("Hardware")
    category_rel: Mapped["Category | None"] = relationship("Category", back_populates="services")
    environment_rel: Mapped["Environment | None"] = relationship("Environment", back_populates="services", foreign_keys=[environment_id])
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
    gateway_hardware_id: Mapped[int | None] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=True)
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

    compute_unit: Mapped["ComputeUnit"] = relationship("ComputeUnit", back_populates="network_memberships")
    network: Mapped["Network"] = relationship("Network", back_populates="compute_memberships")


class HardwareConnection(Base):
    """Direct hardware-to-hardware physical connection (e.g. switch uplink, crossover cable)."""
    __tablename__ = "hardware_connections"
    __table_args__ = (UniqueConstraint("source_hardware_id", "target_hardware_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False)
    target_hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    source_hardware: Mapped["Hardware"] = relationship("Hardware", foreign_keys=[source_hardware_id], back_populates="outgoing_connections")
    target_hardware: Mapped["Hardware"] = relationship("Hardware", foreign_keys=[target_hardware_id], back_populates="incoming_connections")


# ── Hardware Clusters ────────────────────────────────────────────────────────


class HardwareCluster(Base):
    __tablename__ = "hardware_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    icon_slug: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    members: Mapped[list["HardwareClusterMember"]] = relationship(
        "HardwareClusterMember", back_populates="cluster", cascade="all, delete-orphan"
    )


class HardwareClusterMember(Base):
    __tablename__ = "hardware_cluster_members"
    __table_args__ = (UniqueConstraint("cluster_id", "hardware_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cluster_id: Mapped[int] = mapped_column(Integer, ForeignKey("hardware_clusters.id"), nullable=False)
    hardware_id: Mapped[int] = mapped_column(Integer, ForeignKey(_FK_HARDWARE_ID), nullable=False)
    role: Mapped[str | None] = mapped_column(String)

    cluster: Mapped["HardwareCluster"] = relationship("HardwareCluster", back_populates="members")
    hardware: Mapped["Hardware"] = relationship("Hardware", back_populates="cluster_memberships")


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
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship("Service", back_populates="misc_links")
    misc_item: Mapped["MiscItem"] = relationship("MiscItem", back_populates="service_links")


# ── External Nodes (Off-Prem / Cloud) ─────────────────────────────────────────


class ExternalNode(Base):
    __tablename__ = "external_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String)          # e.g. 'Hetzner', 'AWS', 'Cloudflare'
    kind: Mapped[str | None] = mapped_column(String)              # 'vps', 'managed_db', 'saas', 'vpn_gateway', etc.
    region: Mapped[str | None] = mapped_column(String)            # 'us-west-2', 'nbg1', 'global', etc.
    ip_address: Mapped[str | None] = mapped_column(String)        # primary IP or hostname
    icon_slug: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(String)       # 'prod', 'lab', 'shared'
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

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
    external_node_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_nodes.id", ondelete="CASCADE"), nullable=False)
    network_id: Mapped[int] = mapped_column(Integer, ForeignKey("networks.id", ondelete="CASCADE"), nullable=False)
    link_type: Mapped[str | None] = mapped_column(String)    # 'vpn', 'wan', 'wireguard', 'reverse_proxy', etc.
    notes: Mapped[str | None] = mapped_column(Text)
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    external_node: Mapped["ExternalNode"] = relationship("ExternalNode", back_populates="network_links")
    network: Mapped["Network"] = relationship("Network")


class ServiceExternalNode(Base):
    __tablename__ = "service_external_nodes"
    __table_args__ = (UniqueConstraint("service_id", "external_node_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[int] = mapped_column(Integer, ForeignKey("services.id", ondelete="CASCADE"), nullable=False)
    external_node_id: Mapped[int] = mapped_column(Integer, ForeignKey("external_nodes.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str | None] = mapped_column(String)      # 'db', 'auth', 'cache', 'upstream_api', etc.
    connection_type: Mapped[str | None] = mapped_column(String, default="ethernet")
    bandwidth_mbps: Mapped[int | None] = mapped_column(Integer)

    service: Mapped["Service"] = relationship("Service")
    external_node: Mapped["ExternalNode"] = relationship("ExternalNode", back_populates="service_links")


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
    show_header_widgets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_time_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_weather_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weather_location: Mapped[str] = mapped_column(String, nullable=False, default="Phoenix, AZ")
    auth_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    jwt_secret: Mapped[str | None] = mapped_column(Text)
    session_timeout_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    # Branding
    app_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    favicon_path: Mapped[str | None] = mapped_column(Text)
    login_logo_path: Mapped[str | None] = mapped_column(Text)
    login_bg_path: Mapped[str | None] = mapped_column(Text)
    primary_color: Mapped[str] = mapped_column(String, nullable=False, default="#00d4ff")
    accent_colors: Mapped[str | None] = mapped_column(Text, default='["#ff6b6b","#4ecdc4"]')  # JSON array
    # Advanced Theming
    theme_preset: Mapped[str] = mapped_column(String, nullable=False, default="cyberpunk-neon")
    custom_colors: Mapped[str | None] = mapped_column(Text)  # JSON: {primary,secondary,accent1,accent2,background,surface}
    # External nodes
    show_external_nodes_on_map: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Timezone preference (IANA name, e.g. "America/Denver")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    # Auto-Discovery settings
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_auto_merge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_default_cidr: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_nmap_args: Mapped[str] = mapped_column(String, nullable=False, default="-sV -O --open -T4")
    discovery_snmp_community: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_schedule_cron: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_http_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovery_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    scan_ack_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Font preferences
    ui_font: Mapped[str] = mapped_column(String, nullable=False, default="inter")
    ui_font_size: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ── Auto Discovery ────────────────────────────────────────────────────────────


class DiscoveryProfile(Base):
    __tablename__ = "discovery_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cidr: Mapped[str] = mapped_column(String, nullable=False)
    scan_types: Mapped[str] = mapped_column(String, default='["nmap"]')
    nmap_arguments: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_community_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_version: Mapped[str] = mapped_column(String, default="2c")
    snmp_port: Mapped[int] = mapped_column(Integer, default=161)
    schedule_cron: Mapped[str | None] = mapped_column(String, nullable=True)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    last_run: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    jobs: Mapped[list["ScanJob"]] = relationship("ScanJob", back_populates="profile")


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    profile_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("discovery_profiles.id"), nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    target_cidr: Mapped[str] = mapped_column(String, nullable=False)
    scan_types_json: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued")
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    hosts_found: Mapped[int] = mapped_column(Integer, default=0)
    hosts_new: Mapped[int] = mapped_column(Integer, default=0)
    hosts_updated: Mapped[int] = mapped_column(Integer, default=0)
    hosts_conflict: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(String, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String, default="api")
    progress_phase: Mapped[str] = mapped_column(String, default="queued")
    progress_message: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    profile: Mapped["DiscoveryProfile | None"] = relationship("DiscoveryProfile", back_populates="jobs")
    results: Mapped[list["ScanResult"]] = relationship("ScanResult", back_populates="job")


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scan_jobs.id"), nullable=False)
    ip_address: Mapped[str] = mapped_column(String, nullable=False)
    mac_address: Mapped[str | None] = mapped_column(String, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    open_ports_json: Mapped[str | None] = mapped_column(String, nullable=True)
    os_family: Mapped[str | None] = mapped_column(String, nullable=True)
    os_vendor: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_name: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_sys_descr: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_interfaces_json: Mapped[str | None] = mapped_column(String, nullable=True)
    snmp_storage_json: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_nmap_xml: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str] = mapped_column(String, default="new")
    conflicts_json: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    matched_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    merge_status: Mapped[str] = mapped_column(String, default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)

    job: Mapped["ScanJob"] = relationship("ScanJob", back_populates="results")


# ── Users ─────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    gravatar_hash: Mapped[str | None] = mapped_column(Text)
    profile_photo: Mapped[str | None] = mapped_column(Text)  # relative path to uploaded file
    display_name: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, default="en")
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
    actor:       Mapped[str | None]   = mapped_column(String, default="anonymous")
    actor_gravatar_hash: Mapped[str | None] = mapped_column(String)
    entity_type: Mapped[str | None]   = mapped_column(String)
    entity_id:   Mapped[int | None]   = mapped_column(Integer)
    old_value:   Mapped[str | None]   = mapped_column(Text)
    new_value:   Mapped[str | None]   = mapped_column(Text)
    user_agent:  Mapped[str | None]   = mapped_column(String)
    ip_address:  Mapped[str | None]   = mapped_column(String)
    details:     Mapped[str | None]   = mapped_column(Text)
    status_code: Mapped[int | None]   = mapped_column(Integer)   # HTTP response status (added for error tracking)
    created_at_utc: Mapped[str | None] = mapped_column(String)   # ISO 8601 UTC string; canonical timestamp for frontend display
    # Feature 6: structured audit fields
    actor_id:    Mapped[int | None]   = mapped_column(Integer)
    actor_name:  Mapped[str | None]   = mapped_column(String, default="admin")
    entity_name: Mapped[str | None]   = mapped_column(String)    # denormalised name at write time
    diff:        Mapped[str | None]   = mapped_column(Text)       # JSON: {"before": {...}, "after": {...}}
    severity:    Mapped[str | None]   = mapped_column(String, default="info")  # info | warn | error


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
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


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

