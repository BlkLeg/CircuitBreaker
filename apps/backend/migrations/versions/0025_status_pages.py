"""add status_pages, status_groups, status_history

Revision ID: 0025_status_pages
Revises: 0024_rbac_scopes_demo
Create Date: 2026-03-09

"""

import sqlalchemy as sa
from alembic import op

revision = "0025_status_pages"
down_revision = "0024_rbac_scopes_demo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "status_pages" not in tables:
        op.create_table(
            "status_pages",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("config", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )

    if "status_groups" not in tables:
        op.create_table(
            "status_groups",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("status_page_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("nodes", sa.Text(), nullable=True),
            sa.Column("services", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["status_page_id"], ["status_pages.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_status_groups_status_page_id"),
            "status_groups",
            ["status_page_id"],
            unique=False,
        )

    if "status_history" not in tables:
        op.create_table(
            "status_history",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("group_id", sa.Integer(), nullable=False),
            sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("overall_status", sa.String(), nullable=False),
            sa.Column("uptime_pct", sa.Float(), nullable=False),
            sa.Column("avg_ping", sa.Float(), nullable=True),
            sa.Column("metrics", sa.Text(), nullable=True),
            sa.Column("raw_telemetry", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["group_id"], ["status_groups.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_status_history_group_id"),
            "status_history",
            ["group_id"],
            unique=False,
        )
        op.create_index(
            "ix_status_history_group_timestamp",
            "status_history",
            ["group_id", "timestamp"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_status_history_group_timestamp", table_name="status_history")
    op.drop_index(op.f("ix_status_history_group_id"), table_name="status_history")
    op.drop_table("status_history")
    op.drop_index(op.f("ix_status_groups_status_page_id"), table_name="status_groups")
    op.drop_table("status_groups")
    op.drop_table("status_pages")
