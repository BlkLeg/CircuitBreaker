"""Add integration_id FK to status_pages for auto-provisioned pages.

Revision ID: 0054_status_page_integration_id
Revises: 0053_public_status_page_and_monitor_events
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0054_status_page_integration_id"
down_revision = "0053_public_status_page_and_monitor_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)

    if "integration_id" not in {c["name"] for c in insp.get_columns("status_pages")}:
        op.add_column(
            "status_pages",
            sa.Column("integration_id", sa.Integer(), nullable=True),
        )
    existing_fks = {fk["name"] for fk in insp.get_foreign_keys("status_pages")}
    if "fk_status_pages_integration_id" not in existing_fks:
        op.create_foreign_key(
            "fk_status_pages_integration_id",
            "status_pages",
            "integrations",
            ["integration_id"],
            ["id"],
            ondelete="SET NULL",
        )
    existing_indexes = {idx["name"] for idx in insp.get_indexes("status_pages")}
    if "ix_status_pages_integration_id" not in existing_indexes:
        op.create_index(
            "ix_status_pages_integration_id",
            "status_pages",
            ["integration_id"],
            unique=True,
        )


def downgrade() -> None:
    op.drop_index("ix_status_pages_integration_id", table_name="status_pages")
    op.drop_constraint("fk_status_pages_integration_id", "status_pages", type_="foreignkey")
    op.drop_column("status_pages", "integration_id")
