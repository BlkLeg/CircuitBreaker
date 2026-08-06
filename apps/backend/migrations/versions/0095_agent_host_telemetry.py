"""Agent host telemetry persistence and Hardware attribution.

Revision ID: 0095_agent_host_telemetry
Revises: 0094_agent_server_key_rotation
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = "0095_agent_host_telemetry"
down_revision = "0094_agent_server_key_rotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    tables = set(inspector.get_table_names())
    hardware_columns = {column["name"] for column in inspector.get_columns("hardware_live_metrics")}
    # Fresh installs build current Base.metadata in 0001 before replaying
    # additive migrations. In that path the complete Slice 2 schema already
    # exists; only the Timescale conversion remains to be applied here.
    if {
        "agent_host_samples",
        "agent_host_sample_hourly",
        "agent_capability_readiness",
    }.issubset(tables) and {"agent_id", "agent_sample_id"}.issubset(hardware_columns):
        if conn.dialect.name == "postgresql":
            op.execute(
                "SELECT create_hypertable('agent_host_samples', 'collected_at', "
                "if_not_exists => TRUE, migrate_data => TRUE)"
            )
        return
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "agent_host_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("hardware_id", sa.Integer(), nullable=True),
        sa.Column("sample_id", sa.String(32), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cpu_pct", sa.Float()),
        sa.Column("mem_pct", sa.Float()),
        sa.Column("root_disk_pct", sa.Float()),
        sa.Column("net_rx_bps", sa.Float()),
        sa.Column("net_tx_bps", sa.Float()),
        sa.Column("max_temp_c", sa.Float()),
        sa.Column("load_1", sa.Float()),
        sa.Column("uptime_s", sa.BigInteger()),
        sa.Column("raw", json_type, nullable=False),
        sa.Column("projected_at", sa.DateTime(timezone=True)),
        sa.Column("projection_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["hardware_id"], ["hardware.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", "collected_at"),
        sa.UniqueConstraint("agent_id", "sample_id", "collected_at", name="uq_agent_host_sample"),
    )
    op.create_index(
        "ix_agent_host_samples_agent_time", "agent_host_samples", ["agent_id", "collected_at"]
    )
    op.create_index(
        "ix_agent_host_samples_projection", "agent_host_samples", ["projected_at", "collected_at"]
    )
    op.create_table(
        "agent_host_sample_hourly",
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("summary", json_type, nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "bucket_at"),
    )
    op.create_table(
        "agent_capability_readiness",
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("collector", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(512)),
        sa.Column("remediation", sa.String(512)),
        sa.Column("missing", json_type, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "collector"),
    )
    op.create_index(
        "ix_agent_readiness_agent_time", "agent_capability_readiness", ["agent_id", "updated_at"]
    )
    is_postgres = conn.dialect.name == "postgresql"
    if is_postgres:
        # Timescale rejects ALTER TABLE/constraint operations while native
        # compression is enabled. Preserve the existing policy around this
        # short schema change and restore it immediately afterwards.
        op.execute("ALTER TABLE hardware_live_metrics SET (timescaledb.compress = false)")
    with op.batch_alter_table("hardware_live_metrics") as batch:
        batch.add_column(sa.Column("agent_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("agent_sample_id", sa.String(32), nullable=True))
        batch.create_foreign_key(
            "fk_hardware_metric_agent", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_hardware_live_metrics_agent_time", ["agent_id", "collected_at"])
        batch.create_index(
            "uq_hardware_live_metrics_agent_sample",
            ["agent_id", "agent_sample_id", "collected_at"],
            unique=True,
        )
    if is_postgres:
        op.execute(
            "ALTER TABLE hardware_live_metrics SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'hardware_id,agent_id', "
            "timescaledb.compress_orderby = 'collected_at DESC')"
        )
        op.execute(
            "SELECT create_hypertable('agent_host_samples', 'collected_at', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )


def downgrade() -> None:
    conn = op.get_bind()
    is_postgres = conn.dialect.name == "postgresql"
    inspector = sa_inspect(conn)
    agent_fk = next(
        (
            fk["name"]
            for fk in inspector.get_foreign_keys("hardware_live_metrics")
            if fk.get("constrained_columns") == ["agent_id"]
        ),
        None,
    )
    if is_postgres:
        op.execute("ALTER TABLE hardware_live_metrics SET (timescaledb.compress = false)")
    with op.batch_alter_table("hardware_live_metrics") as batch:
        batch.drop_index("uq_hardware_live_metrics_agent_sample")
        batch.drop_index("ix_hardware_live_metrics_agent_time")
        if agent_fk:
            batch.drop_constraint(agent_fk, type_="foreignkey")
        batch.drop_column("agent_sample_id")
        batch.drop_column("agent_id")
    if is_postgres:
        op.execute(
            "ALTER TABLE hardware_live_metrics SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'hardware_id', "
            "timescaledb.compress_orderby = 'collected_at DESC')"
        )
    op.drop_index("ix_agent_readiness_agent_time", table_name="agent_capability_readiness")
    op.drop_table("agent_capability_readiness")
    op.drop_table("agent_host_sample_hourly")
    op.drop_index("ix_agent_host_samples_projection", table_name="agent_host_samples")
    op.drop_index("ix_agent_host_samples_agent_time", table_name="agent_host_samples")
    op.drop_table("agent_host_samples")
