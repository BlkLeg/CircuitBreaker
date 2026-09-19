"""Add source-scoped Docker sync state and inventory provenance.

Revision ID: 0112_docker_sources
Revises: 0111_notification_delivery
Create Date: 2026-09-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = "0112_docker_sources"
down_revision = "0111_notification_delivery"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa_inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    """Index names already on `table`, for the same reason `_columns` exists.

    A fresh install gets its whole schema from `0001_init`, which calls
    `create_all()` over the *live* ORM metadata — so every index and foreign key
    this revision adds is already present by the time it runs, and an unguarded
    `create_index` fails the upgrade with DuplicateTable. Guarding the columns
    but not the indexes left `alembic upgrade head` broken on any database that
    had not already been through 0111.
    """
    return {index["name"] for index in sa_inspect(op.get_bind()).get_indexes(table)}


def _foreign_keys(table: str) -> set[str]:
    """Foreign-key constraint names already on `table`. See `_indexes`."""
    return {fk["name"] for fk in sa_inspect(op.get_bind()).get_foreign_keys(table)}


def _drop_single_column_unique(table: str, column: str) -> None:
    for constraint in sa_inspect(op.get_bind()).get_unique_constraints(table):
        if constraint.get("column_names") == [column] and constraint.get("name"):
            op.drop_constraint(str(constraint["name"]), table, type_="unique")


def _assert_no_native_duplicates(table: str, column: str) -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT {column} FROM {table} "
                f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            f"Cannot source-scope Docker identity: duplicate {table}.{column} values exist"
        )


def upgrade() -> None:
    inspector = sa_inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "docker_sources" not in tables:
        op.create_table(
            "docker_sources",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("identity", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("connection_kind", sa.String(length=16), nullable=False),
            sa.Column("endpoint_hint", sa.String(length=255), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
            sa.Column("parent_type", sa.String(length=16), nullable=True),
            sa.Column("parent_id", sa.Integer(), nullable=True),
            sa.Column(
                "parent_provenance",
                sa.String(length=16),
                server_default="unresolved",
                nullable=False,
            ),
            sa.Column("parent_assigned_by", sa.String(length=200), nullable=True),
            sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("identity", name="uq_docker_sources_identity"),
            sa.CheckConstraint(
                "(parent_type IS NULL AND parent_id IS NULL) OR "
                "(parent_type IN ('hardware', 'compute') AND parent_id IS NOT NULL)",
                name="ck_docker_sources_parent_pair",
            ),
        )
    if "docker_sync_runs" not in tables:
        op.create_table(
            "docker_sync_runs",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.Integer(), nullable=False),
            sa.Column("source_revision", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
            sa.Column("triggered_by", sa.String(length=200), nullable=True),
            sa.Column("lease_token", sa.String(length=32), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "containers_complete",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column("networks_complete", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("containers_observed", sa.Integer(), server_default="0", nullable=False),
            sa.Column("networks_observed", sa.Integer(), server_default="0", nullable=False),
            sa.Column("containers_created", sa.Integer(), server_default="0", nullable=False),
            sa.Column("containers_updated", sa.Integer(), server_default="0", nullable=False),
            sa.Column("containers_stopped", sa.Integer(), server_default="0", nullable=False),
            sa.Column("networks_created", sa.Integer(), server_default="0", nullable=False),
            sa.Column("networks_updated", sa.Integer(), server_default="0", nullable=False),
            sa.Column("conflict_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("reason_code", sa.String(length=64), nullable=True),
            sa.Column("safe_message", sa.String(length=300), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["source_id"], ["docker_sources.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'interrupted')",
                name="ck_docker_sync_runs_status",
            ),
        )
        op.create_index(
            "ix_docker_sync_runs_source_created",
            "docker_sync_runs",
            ["source_id", "created_at"],
        )
        op.create_index(
            "ix_docker_sync_runs_status_lease",
            "docker_sync_runs",
            ["status", "lease_expires_at"],
        )

    service_columns = _columns("services")
    for column in (
        sa.Column("docker_source_id", sa.Integer(), nullable=True),
        sa.Column("docker_workload_key", sa.String(length=512), nullable=True),
        sa.Column(
            "docker_network_ids",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "docker_parent_provenance",
            sa.String(length=16),
            server_default="unresolved",
            nullable=False,
        ),
        sa.Column("docker_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in service_columns:
            op.add_column("services", column)
    if "fk_services_docker_source_id" not in _foreign_keys("services"):
        op.create_foreign_key(
            "fk_services_docker_source_id",
            "services",
            "docker_sources",
            ["docker_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
    _assert_no_native_duplicates("services", "docker_container_id")
    _drop_single_column_unique("services", "docker_container_id")
    service_indexes = _indexes("services")
    if "uq_services_docker_source_container" not in service_indexes:
        op.create_index(
            "uq_services_docker_source_container",
            "services",
            ["docker_source_id", "docker_container_id"],
            unique=True,
        )
    if "uq_services_legacy_docker_container" not in service_indexes:
        op.create_index(
            "uq_services_legacy_docker_container",
            "services",
            ["docker_container_id"],
            unique=True,
            postgresql_where=sa.text(
                "docker_source_id IS NULL AND docker_container_id IS NOT NULL"
            ),
        )

    network_columns = _columns("networks")
    if "docker_source_id" not in network_columns:
        op.add_column("networks", sa.Column("docker_source_id", sa.Integer(), nullable=True))
    if "fk_networks_docker_source_id" not in _foreign_keys("networks"):
        op.create_foreign_key(
            "fk_networks_docker_source_id",
            "networks",
            "docker_sources",
            ["docker_source_id"],
            ["id"],
            ondelete="SET NULL",
        )
    _assert_no_native_duplicates("networks", "docker_network_id")
    _drop_single_column_unique("networks", "docker_network_id")
    network_indexes = _indexes("networks")
    if "uq_networks_docker_source_native" not in network_indexes:
        op.create_index(
            "uq_networks_docker_source_native",
            "networks",
            ["docker_source_id", "docker_network_id"],
            unique=True,
        )
    if "uq_networks_legacy_docker_native" not in network_indexes:
        op.create_index(
            "uq_networks_legacy_docker_native",
            "networks",
            ["docker_network_id"],
            unique=True,
            postgresql_where=sa.text("docker_source_id IS NULL AND docker_network_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_networks_legacy_docker_native", table_name="networks")
    op.drop_index("uq_networks_docker_source_native", table_name="networks")
    op.drop_constraint("fk_networks_docker_source_id", "networks", type_="foreignkey")
    op.drop_column("networks", "docker_source_id")
    op.create_unique_constraint("uq_networks_docker_network_id", "networks", ["docker_network_id"])
    op.drop_index("uq_services_docker_source_container", table_name="services")
    op.drop_index("uq_services_legacy_docker_container", table_name="services")
    op.drop_constraint("fk_services_docker_source_id", "services", type_="foreignkey")
    for column in (
        "docker_last_seen_at",
        "docker_parent_provenance",
        "docker_network_ids",
        "docker_workload_key",
        "docker_source_id",
    ):
        op.drop_column("services", column)
    op.create_unique_constraint(
        "uq_services_docker_container_id", "services", ["docker_container_id"]
    )
    op.drop_table("docker_sync_runs")
    op.drop_table("docker_sources")
