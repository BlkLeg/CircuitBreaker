"""Add integrations and integration_monitors tables.

Revision ID: 0051_integrations
Revises: 0050_timescaledb_hypertables
Create Date: 2026-03-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_integrations"
down_revision = "0050_timescaledb_hypertables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    if not conn.dialect.has_table(conn, "integrations"):
        op.create_table(
            "integrations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("type", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("base_url", sa.String(512), nullable=False),
            sa.Column("api_key", sa.Text(), nullable=True),
            sa.Column("sync_interval_s", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sync_status", sa.String(16), nullable=False, server_default="never"),
            sa.Column("sync_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if not conn.dialect.has_table(conn, "integration_monitors"):
        op.create_table(
            "integration_monitors",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("integration_id", sa.Integer(), nullable=False),
            sa.Column("external_id", sa.String(128), nullable=False),
            sa.Column("name", sa.String(256), nullable=False),
            sa.Column("url", sa.String(512), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("uptime_7d", sa.Float(), nullable=True),
            sa.Column("uptime_30d", sa.Float(), nullable=True),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["integration_id"],
                ["integrations.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("integration_id", "external_id", name="uq_intmon_ext_id"),
        )
        op.create_index(
            "ix_integration_monitors_integration_id",
            "integration_monitors",
            ["integration_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_integration_monitors_integration_id", table_name="integration_monitors")
    op.drop_table("integration_monitors")
    op.drop_table("integrations")
