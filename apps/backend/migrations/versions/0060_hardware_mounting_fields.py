"""Add mounting_orientation and side_rail fields to hardware table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0060_hardware_mounting_fields"
down_revision = "0059_uk_enrichment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    existing_cols = {c["name"] for c in insp.get_columns("hardware")}

    if "mounting_orientation" not in existing_cols:
        op.add_column(
            "hardware",
            sa.Column(
                "mounting_orientation", sa.String(), nullable=True, server_default="horizontal"
            ),
        )
    if "side_rail" not in existing_cols:
        op.add_column(
            "hardware",
            sa.Column("side_rail", sa.String(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("hardware", "side_rail")
    op.drop_column("hardware", "mounting_orientation")
