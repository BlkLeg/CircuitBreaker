"""Add node_relations table for generic graph edges.

Revision ID: 0037_node_relations
Revises: 0036_ipam_vlans_sites
Create Date: 2026-03-11

Provides a unified, polymorphic edge table for the topology graph.
Coexists with the existing typed join tables (hardware_networks, etc.)
which remain the source of truth for typed relationships.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0037_node_relations"
down_revision = "0036_ipam_vlans_sites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("node_relations"):
        return

    op.create_table(
        "node_relations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "team_id",
            sa.Integer,
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.BigInteger, nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.BigInteger, nullable=False),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "target_type",
            "target_id",
            "relation_type",
            name="uq_node_rel_edge",
        ),
    )
    op.create_index(
        "ix_noderel_source",
        "node_relations",
        ["team_id", "source_type", "source_id"],
    )
    op.create_index(
        "ix_noderel_target",
        "node_relations",
        ["team_id", "target_type", "target_id"],
    )
    op.create_index(
        "ix_noderel_relation_type",
        "node_relations",
        ["relation_type"],
    )


def downgrade() -> None:
    op.drop_table("node_relations")
