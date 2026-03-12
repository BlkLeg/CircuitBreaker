"""Add partitioned audit_log table and DB-level audit triggers.

Revision ID: 0039_audit_triggers
Revises: 0038_rename_teams_to_tenants
Create Date: 2026-03-11

Creates a range-partitioned audit_log table (by timestamp) with monthly
partitions and a generic audit_trigger() function that captures INSERT,
UPDATE, and DELETE operations on key entity tables.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0039_audit_triggers"
down_revision = "0038_rename_teams_to_tenants"
branch_labels = None
depends_on = None

_TRIGGER_TABLES = [
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
    "integration_configs",
]

_AUDIT_TRIGGER_FUNC = """\
CREATE OR REPLACE FUNCTION audit_trigger()
RETURNS TRIGGER AS $$
DECLARE
    _tenant_id INT;
    _entity_id BIGINT;
BEGIN
    -- Extract tenant_id if the column exists on the source table
    IF TG_OP = 'DELETE' THEN
        BEGIN
            EXECUTE format('SELECT ($1).%I', 'tenant_id') INTO _tenant_id USING OLD;
        EXCEPTION WHEN undefined_column THEN
            _tenant_id := NULL;
        END;
        _entity_id := OLD.id;
    ELSE
        BEGIN
            EXECUTE format('SELECT ($1).%I', 'tenant_id') INTO _tenant_id USING NEW;
        EXCEPTION WHEN undefined_column THEN
            _tenant_id := NULL;
        END;
        _entity_id := NEW.id;
    END IF;

    INSERT INTO audit_log (tenant_id, entity_type, entity_id, action, old_data, new_data)
    VALUES (
        _tenant_id,
        TG_TABLE_NAME,
        _entity_id,
        TG_OP,
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN row_to_json(OLD) END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN row_to_json(NEW) END
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _partition_name(year: int, month: int) -> str:
    return f"audit_log_{year}_{month:02d}"


def _create_partition(year: int, month: int) -> None:
    """Create a single monthly partition for audit_log."""
    name = _partition_name(year, month)
    start = f"{year}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{month + 1:02d}-01"
    op.execute(
        sa.text(
            f"CREATE TABLE IF NOT EXISTS {name} PARTITION OF audit_log "
            f"FOR VALUES FROM ('{start}') TO ('{end}')"
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("audit_log"):
        op.execute(
            sa.text(
                "CREATE TABLE audit_log ("
                "  id BIGSERIAL,"
                "  tenant_id INT,"
                "  entity_type VARCHAR(32),"
                "  entity_id BIGINT,"
                "  action VARCHAR(16),"
                "  user_id INT,"
                "  old_data JSONB,"
                "  new_data JSONB,"
                "  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()"
                ") PARTITION BY RANGE (timestamp)"
            )
        )

        now = datetime.utcnow()
        for offset in range(6):
            dt = now + timedelta(days=30 * offset)
            _create_partition(dt.year, dt.month)

        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_audit_log_tenant_ts "
                "ON audit_log (tenant_id, timestamp DESC)"
            )
        )
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_audit_log_entity "
                "ON audit_log (entity_type, entity_id)"
            )
        )

    # Create trigger function
    op.execute(sa.text(_AUDIT_TRIGGER_FUNC))

    # Attach triggers to entity tables
    existing_tables = set(insp.get_table_names())
    for table in _TRIGGER_TABLES:
        if table not in existing_tables:
            continue
        trigger_name = f"{table}_audit_trigger"
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}"))
        op.execute(
            sa.text(
                f"CREATE TRIGGER {trigger_name} "
                f"AFTER INSERT OR UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION audit_trigger()"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    for table in _TRIGGER_TABLES:
        if table not in existing_tables:
            continue
        trigger_name = f"{table}_audit_trigger"
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}"))

    op.execute(sa.text("DROP FUNCTION IF EXISTS audit_trigger() CASCADE"))

    if insp.has_table("audit_log"):
        op.execute(sa.text("DROP TABLE IF EXISTS audit_log CASCADE"))
