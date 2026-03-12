"""Rename teams -> tenants for proper multi-tenancy semantics.

Revision ID: 0038_rename_teams_to_tenants
Revises: 0037_node_relations
Create Date: 2026-03-11

Renames the teams table and all team_id FK columns to tenants/tenant_id.
Adds a slug column to tenants and a tenant_id column to users.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_rename_teams_to_tenants"
down_revision = "0037_node_relations"
branch_labels = None
depends_on = None

_TABLES_WITH_TEAM_ID = [
    "hardware",
    "services",
    "networks",
    "hardware_clusters",
    "external_nodes",
    "integration_configs",
    "scan_jobs",
    "topologies",
    "ip_addresses",
    "vlans",
    "sites",
    "node_relations",
]


def _table_exists(bind, table: str) -> bool:
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = :t"
        ),
        {"t": table},
    )
    return r.scalar() is not None


def _column_exists(bind, table: str, column: str) -> bool:
    r = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return r.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()

    # Rename tables
    if _table_exists(bind, "teams") and not _table_exists(bind, "tenants"):
        op.rename_table("teams", "tenants")
    if _table_exists(bind, "team_members") and not _table_exists(bind, "tenant_members"):
        op.rename_table("team_members", "tenant_members")

    # Rename columns in tenant_members
    if _table_exists(bind, "tenant_members"):
        if _column_exists(bind, "tenant_members", "team_id") and not _column_exists(
            bind, "tenant_members", "tenant_id"
        ):
            op.alter_column("tenant_members", "team_id", new_column_name="tenant_id")
        if _column_exists(bind, "tenant_members", "team_role") and not _column_exists(
            bind, "tenant_members", "tenant_role"
        ):
            op.alter_column("tenant_members", "team_role", new_column_name="tenant_role")

    # Rename team_id -> tenant_id on all entity tables
    for table in _TABLES_WITH_TEAM_ID:
        if not _table_exists(bind, table):
            continue
        if _column_exists(bind, table, "team_id") and not _column_exists(bind, table, "tenant_id"):
            op.alter_column(table, "team_id", new_column_name="tenant_id")

    # Add slug column to tenants
    if _table_exists(bind, "tenants") and not _column_exists(bind, "tenants", "slug"):
        op.add_column(
            "tenants",
            sa.Column("slug", sa.String(32), nullable=True, unique=True),
        )
        op.execute(
            sa.text("UPDATE tenants SET slug = lower(replace(name, ' ', '-')) WHERE slug IS NULL")
        )

    # Add tenant_id to users
    if _table_exists(bind, "users") and not _column_exists(bind, "users", "tenant_id"):
        op.add_column(
            "users",
            sa.Column(
                "tenant_id",
                sa.Integer,
                sa.ForeignKey("tenants.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        # Backfill using the column name that actually exists now
        tm_col = "tenant_id" if _column_exists(bind, "tenant_members", "tenant_id") else "team_id"
        op.execute(
            sa.text(
                f"UPDATE users SET tenant_id = tm.{tm_col} "
                f"FROM tenant_members tm WHERE users.id = tm.user_id "
                f"AND users.tenant_id IS NULL"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "users") and _column_exists(bind, "users", "tenant_id"):
        op.drop_column("users", "tenant_id")

    if _table_exists(bind, "tenants") and _column_exists(bind, "tenants", "slug"):
        op.drop_column("tenants", "slug")

    for table in reversed(_TABLES_WITH_TEAM_ID):
        if not _table_exists(bind, table):
            continue
        if _column_exists(bind, table, "tenant_id") and not _column_exists(bind, table, "team_id"):
            op.alter_column(table, "tenant_id", new_column_name="team_id")

    if _table_exists(bind, "tenant_members"):
        if _column_exists(bind, "tenant_members", "tenant_id") and not _column_exists(
            bind, "tenant_members", "team_id"
        ):
            op.alter_column("tenant_members", "tenant_id", new_column_name="team_id")
        if _column_exists(bind, "tenant_members", "tenant_role") and not _column_exists(
            bind, "tenant_members", "team_role"
        ):
            op.alter_column("tenant_members", "tenant_role", new_column_name="team_role")

    if _table_exists(bind, "tenant_members") and not _table_exists(bind, "team_members"):
        op.rename_table("tenant_members", "team_members")
    if _table_exists(bind, "tenants") and not _table_exists(bind, "teams"):
        op.rename_table("tenants", "teams")
