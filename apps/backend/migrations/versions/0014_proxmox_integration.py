"""Add Proxmox VE integration support

Revision ID: a3b4c5d6e7fb
Revises: a3b4c5d6e7fa
Create Date: 2026-03-07 22:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7fb"
down_revision = "a3b4c5d6e7fa"
branch_labels = None
depends_on = None


def upgrade():
    # ── integration_configs table ──────────────────────────────────────────
    op.create_table(
        "integration_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("config_url", sa.String(), nullable=False),
        sa.Column("credential_id", sa.Integer(), sa.ForeignKey("credentials.id"), nullable=True),
        sa.Column("cluster_name", sa.String(), nullable=True),
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sync_interval_s", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(), nullable=True),
        sa.Column("extra_config", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── telemetry_timeseries table ─────────────────────────────────────────
    op.create_table(
        "telemetry_timeseries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=True, server_default="proxmox"),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_ts_entity",
        "telemetry_timeseries",
        ["entity_type", "entity_id", "metric", "ts"],
    )

    # ── hardware additions ─────────────────────────────────────────────────
    op.add_column("hardware", sa.Column("proxmox_node_name", sa.String(), nullable=True))
    op.add_column(
        "hardware",
        sa.Column(
            "integration_config_id",
            sa.Integer(),
            sa.ForeignKey("integration_configs.id"),
            nullable=True,
        ),
    )

    # ── compute_units additions ────────────────────────────────────────────
    op.add_column("compute_units", sa.Column("proxmox_vmid", sa.Integer(), nullable=True))
    op.add_column("compute_units", sa.Column("proxmox_type", sa.String(), nullable=True))
    op.add_column("compute_units", sa.Column("proxmox_config", sa.Text(), nullable=True))
    op.add_column("compute_units", sa.Column("proxmox_status", sa.Text(), nullable=True))
    op.add_column(
        "compute_units",
        sa.Column(
            "integration_config_id",
            sa.Integer(),
            sa.ForeignKey("integration_configs.id"),
            nullable=True,
        ),
    )

    # ── hardware_clusters addition ─────────────────────────────────────────
    op.add_column(
        "hardware_clusters",
        sa.Column(
            "integration_config_id",
            sa.Integer(),
            sa.ForeignKey("integration_configs.id"),
            nullable=True,
        ),
    )


def downgrade():
    with op.batch_alter_table("hardware_clusters") as batch_op:
        batch_op.drop_column("integration_config_id")

    with op.batch_alter_table("compute_units") as batch_op:
        batch_op.drop_column("integration_config_id")
        batch_op.drop_column("proxmox_status")
        batch_op.drop_column("proxmox_config")
        batch_op.drop_column("proxmox_type")
        batch_op.drop_column("proxmox_vmid")

    with op.batch_alter_table("hardware") as batch_op:
        batch_op.drop_column("integration_config_id")
        batch_op.drop_column("proxmox_node_name")

    op.drop_index("idx_ts_entity", table_name="telemetry_timeseries")
    op.drop_table("telemetry_timeseries")
    op.drop_table("integration_configs")
