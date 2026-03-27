"""Multi-map support — sort_order, topology_id on graph_layouts, map_pinned_entities."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0065_multi_map"
down_revision = "0064_integrations_base_url_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)

    # 1. Add sort_order to topologies
    if "sort_order" not in {c["name"] for c in insp.get_columns("topologies")}:
        op.add_column(
            "topologies",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )

    # 2. Add topology_id FK to graph_layouts
    if "topology_id" not in {c["name"] for c in insp.get_columns("graph_layouts")}:
        op.add_column(
            "graph_layouts",
            sa.Column(
                "topology_id",
                sa.Integer(),
                sa.ForeignKey("topologies.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
    existing_indexes = {idx["name"] for idx in insp.get_indexes("graph_layouts")}
    if "ix_graph_layouts_topology_id" not in existing_indexes:
        op.create_index("ix_graph_layouts_topology_id", "graph_layouts", ["topology_id"])

    # 3. New map_pinned_entities table
    if not conn.dialect.has_table(conn, "map_pinned_entities"):
        op.create_table(
            "map_pinned_entities",
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("entity_type", "entity_id"),
        )

    # 4. Seed: create default Topology and link existing "default" layout
    result = conn.execute(
        sa.text(
            """
            INSERT INTO topologies (name, is_default, sort_order, created_at, updated_at)
            SELECT 'Main', true, 0, NOW(), NOW()
            WHERE NOT EXISTS (SELECT 1 FROM topologies WHERE is_default = true)
            RETURNING id
            """
        )
    )
    row = result.fetchone()
    if row:
        topo_id = row[0]
    else:
        # Existing default topology
        existing = conn.execute(
            sa.text("SELECT id FROM topologies WHERE is_default = true LIMIT 1")
        ).fetchone()
        topo_id = existing[0] if existing else None

    # Link ALL orphaned layouts to the default topology
    if topo_id:
        conn.execute(
            sa.text("UPDATE graph_layouts SET topology_id = :tid WHERE topology_id IS NULL"),
            {"tid": topo_id},
        )


def downgrade() -> None:
    op.drop_table("map_pinned_entities")
    op.drop_index("ix_graph_layouts_topology_id", table_name="graph_layouts")
    op.drop_column("graph_layouts", "topology_id")
    op.drop_column("topologies", "sort_order")
