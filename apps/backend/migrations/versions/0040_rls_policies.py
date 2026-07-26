"""Enable Row-Level Security on all tenant-scoped tables.

Revision ID: 0040_rls_policies
Revises: 0039_audit_triggers
Create Date: 2026-03-11

Enables RLS and creates USING policies so each query only sees rows whose
tenant_id matches the session variable ``app.current_tenant``.  The
``breaker`` role (used by the app) still has full access via BYPASSRLS or
explicit superuser grant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_rls_policies"
down_revision = "0039_audit_triggers"
branch_labels = None
depends_on = None

_RLS_TABLES = [
    "hardware",
    "services",
    "networks",
    "compute_units",
    "storage",
    "hardware_clusters",
    "external_nodes",
    "ip_addresses",
    "vlans",
    "sites",
    "node_relations",
    "scan_jobs",
    "integration_configs",
    "topologies",
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for table in _RLS_TABLES:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        if "tenant_id" not in cols:
            continue

        policy_name = f"tenant_isolation_{table}"

        op.execute(sa.text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))

        op.execute(sa.text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
        op.execute(
            sa.text(
                f"CREATE POLICY {policy_name} ON {table} "
                f"USING (tenant_id = current_setting('app.current_tenant', true)::int)"
            )
        )

    # Ensure the application role bypasses RLS (it sets the variable itself)
    try:
        op.execute(sa.text("ALTER ROLE breaker SET row_security = off"))
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Could not set row_security=off on breaker role: %s (RLS may block queries)", exc
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for table in reversed(_RLS_TABLES):
        if table not in existing_tables:
            continue
        policy_name = f"tenant_isolation_{table}"
        op.execute(sa.text(f"DROP POLICY IF EXISTS {policy_name} ON {table}"))
        op.execute(sa.text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
