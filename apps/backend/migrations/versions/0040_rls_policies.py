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


def _role_exists(bind: sa.engine.Connection, role_name: str) -> bool:
    result = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role_name})
    return result.scalar() is not None


def _quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


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

    # Ensure the application role bypasses RLS (it sets the variable itself).
    #
    # Resolved from the connection rather than hardcoded, following
    # 0080_app_role_schema_grants: packaging/postinstall.sh generates the role
    # `circuitbreaker` while deploy/setup.sh generates `breaker`, so a literal
    # name is wrong for one of the two installers no matter which is chosen.
    #
    # And checked against pg_roles rather than attempted-and-caught. PostgreSQL
    # aborts the enclosing transaction when a statement fails, so catching the
    # Python exception rolled nothing back: every later statement raised
    # InFailedSqlTransaction and the migration run stopped here, at 0040 of
    # roughly a hundred. The old warning said "RLS may block queries", which read
    # as degradation and was in fact a dead install -- Tier 3's boot check is
    # what finally surfaced it.
    bind = op.get_bind()
    url = bind.engine.url
    role = (url.username or "").strip()
    if role and _role_exists(bind, role):
        op.execute(sa.text(f"ALTER ROLE {_quote_ident(role)} SET row_security = off"))
    else:
        import logging

        logging.getLogger(__name__).warning(
            "No application role resolved from the connection URL (got %r); "
            "skipping row_security=off. RLS may block queries for this role.",
            role,
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
