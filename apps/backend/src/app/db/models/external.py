"""Off-prem and cloud nodes, and how on-prem entities reach them."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

if TYPE_CHECKING:  # relationship targets, resolved by SQLAlchemy's registry at runtime
    from app.db.models.networks import Network
    from app.db.models.services import Service

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
