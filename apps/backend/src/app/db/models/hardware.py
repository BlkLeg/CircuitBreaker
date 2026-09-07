"""Physical machines, the cables between them, and the clusters they form."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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
    from app.db.models.compute import ComputeUnit, Environment
    from app.db.models.integrations import IntegrationMonitor
    from app.db.models.intel import CapacityForecast
    from app.db.models.monitors import HardwareMonitor
    from app.db.models.networks import HardwareNetwork
    from app.db.models.privacy import PrivacyScoreHistory
    from app.db.models.services import Service, Storage

# ── Hardware ────────────────────────────────────────────────────────────────


class Hardware(Base):
    __tablename__ = "hardware"
    __table_args__ = (
        # Migration 0109. The discovery matcher looks a device up by MAC then by
        # IP on every finding, and enrichment adds a third lookup on top; both
        # columns were unindexed, so each classification was a sequential scan.
        # Not unique — duplicate MACs and IPs are tolerated on purpose
        # (`hardware_service`: "Saving both (freeform-first)").
        Index("ix_hardware_mac_address", "mac_address"),
        Index("ix_hardware_ip_address", "ip_address"),
    )

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
    # v0.1.2: telemetry (JSONB as of v0.2.0)
    telemetry_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    telemetry_status: Mapped[str | None] = mapped_column(String, default="unknown")
    telemetry_last_polled: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # v0.1.4: environment registry
    environment_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("environments.id"), nullable=True
    )
    # v0.1.4-cortex: discovery lineage.
    #
    # SET NULL, not the NO ACTION this shipped with (Slice 4 Fix A1, migration
    # `0101_discovery_retention_and_global_pause`). This is a *provenance*
    # pointer: it records which scan result a device was approved from, and
    # every reader already treats it as optional. Under NO ACTION it silently
    # pinned discovery history forever —
    # `discovery_scheduler._purge_old_scan_results_impl` could not delete any
    # expiring result that had been merged into inventory, its `except`
    # swallowed the ForeignKeyViolation, and the whole day's retention rolled
    # back. Losing the pointer when the result ages out is what retention means;
    # the device itself is inventory and is never touched.
    source_scan_result_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scan_results.id", ondelete="SET NULL"), nullable=True
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
    # v0.3.0: machine ID hashing for agent matching
    machine_id_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # v0.4.0: Windscribe privacy metrics
    privacy_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    threat_profile: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
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
    privacy_history: Mapped[list["PrivacyScoreHistory"]] = relationship(
        "PrivacyScoreHistory", back_populates="hardware", cascade="all, delete-orphan"
    )


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
