"""Layer 2 and 3: networks and their members, IPAM, VLANs and sites."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _FK_HARDWARE_ID, _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.compute import ComputeUnit
    from app.db.models.hardware import Hardware
    from app.db.models.services import Service

# ── Networks ────────────────────────────────────────────────────────────────


class Network(Base):
    __tablename__ = "networks"
    __table_args__ = (
        Index(
            "uq_networks_docker_source_native",
            "docker_source_id",
            "docker_network_id",
            unique=True,
        ),
        Index(
            "uq_networks_legacy_docker_native",
            "docker_network_id",
            unique=True,
            postgresql_where=text("docker_source_id IS NULL AND docker_network_id IS NOT NULL"),
        ),
    )

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
    docker_network_id: Mapped[str | None] = mapped_column(String, nullable=True)
    docker_driver: Mapped[str | None] = mapped_column(String, nullable=True)
    is_docker_network: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    docker_source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("docker_sources.id", ondelete="SET NULL"), nullable=True
    )
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
