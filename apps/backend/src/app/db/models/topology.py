"""Saved map layouts, explicit topologies, and the generic graph edges the map draws."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.models._shared import _now
from app.db.session import Base

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
