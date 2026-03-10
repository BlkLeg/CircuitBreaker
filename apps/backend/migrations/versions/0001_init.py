"""Bootstrap the initial PostgreSQL schema for fresh installs.

Revision ID: abd204157b2c
Revises:
Create Date: 2026-03-06 20:51:48.197114
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.models import Base

# revision identifiers, used by Alembic.
revision: str = "abd204157b2c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EXCLUDED_TABLES = {
    "api_tokens",
    "credentials",
    "daily_uptime_stats",
    "integration_configs",
    "listener_events",
    "notification_routes",
    "notification_sinks",
    "oauth_states",
    "status_groups",
    "status_history",
    "status_pages",
    "team_members",
    "teams",
    "telemetry_timeseries",
    "topologies",
    "topology_edges",
    "topology_nodes",
    "user_invites",
    "user_sessions",
    "webhook_deliveries",
    "webhook_rules",
}

_EXCLUDED_COLUMNS: dict[str, set[str]] = {
    "app_settings": {
        "arp_enabled",
        "deep_dive_max_parallel",
        "listener_enabled",
        "mdns_enabled",
        "prober_interval_minutes",
        "scan_aggressiveness",
        "self_cluster_enabled",
        "ssdp_enabled",
        "tcp_probe_enabled",
    },
    "compute_units": {
        "integration_config_id",
        "proxmox_config",
        "proxmox_status",
        "proxmox_type",
        "proxmox_vmid",
    },
    "discovery_profiles": {"vlan_ids"},
    "external_nodes": {"team_id"},
    "hardware": {"integration_config_id", "proxmox_node_name", "team_id"},
    "hardware_cluster_members": {"member_type", "service_id"},
    "hardware_clusters": {"integration_config_id", "team_id", "type"},
    "logs": {"log_hash", "previous_hash", "role_at_time", "session_id"},
    "networks": {"team_id"},
    "scan_jobs": {"network_ids", "source_type", "team_id", "vlan_ids"},
    "scan_results": {"banner", "network_id", "os_accuracy", "source_type", "vlan_id"},
    "services": {"docker_labels", "team_id"},
    "storage": {"integration_config_id", "proxmox_storage_name"},
    "tags": {"color"},
    "users": {
        "backup_codes",
        "demo_expires",
        "force_password_change",
        "invited_by",
        "locked_until",
        "login_attempts",
        "masquerade_target",
        "mfa_enabled",
        "oauth_tokens",
        "provider",
        "role",
        "scopes",
        "totp_secret",
    },
}

_NULLABLE_OVERRIDES: dict[str, dict[str, bool]] = {
    "hardware_cluster_members": {"hardware_id": False},
}


def _copy_server_default(column: sa.Column) -> object | None:
    if column.server_default is None:
        return None
    return column.server_default.arg


def _should_copy_fk(source_table: str, fk: sa.ForeignKey) -> bool:
    target_table, target_column = fk.target_fullname.split(".", 1)
    if target_table in _EXCLUDED_TABLES:
        return False
    if target_column in _EXCLUDED_COLUMNS.get(target_table, set()):
        return False
    return source_table != "hardware_cluster_members"


def _copy_column(table_name: str, column: sa.Column) -> sa.Column:
    fk_args = []
    for fk in column.foreign_keys:
        if _should_copy_fk(table_name, fk):
            fk_args.append(sa.ForeignKey(fk.target_fullname, ondelete=fk.ondelete))

    return sa.Column(
        column.name,
        column.type,
        *fk_args,
        primary_key=column.primary_key,
        nullable=_NULLABLE_OVERRIDES.get(table_name, {}).get(column.name, column.nullable),
        unique=column.unique,
        # Re-create indexes from table.indexes below so index=True columns do not
        # produce duplicate named indexes during metadata.create_all().
        index=False,
        server_default=_copy_server_default(column),
        comment=column.comment,
    )


def _build_bootstrap_metadata() -> sa.MetaData:
    bootstrap_metadata = sa.MetaData(naming_convention=Base.metadata.naming_convention)
    included_tables = {
        table_name for table_name in Base.metadata.tables if table_name not in _EXCLUDED_TABLES
    }

    for table in Base.metadata.tables.values():
        if table.name not in included_tables:
            continue

        excluded_columns = _EXCLUDED_COLUMNS.get(table.name, set())
        copied_columns = [
            _copy_column(table.name, column)
            for column in table.columns
            if column.name not in excluded_columns
        ]
        new_table = sa.Table(table.name, bootstrap_metadata, *copied_columns)

        for constraint in table.constraints:
            if not isinstance(constraint, sa.UniqueConstraint):
                continue
            column_names = [column.name for column in constraint.columns]
            if len(column_names) <= 1:
                continue
            if any(name in excluded_columns for name in column_names):
                continue
            new_table.append_constraint(sa.UniqueConstraint(*column_names, name=constraint.name))

        for index in table.indexes:
            column_names = [column.name for column in index.columns]
            if any(name in excluded_columns for name in column_names):
                continue
            sa.Index(index.name, *(new_table.c[name] for name in column_names), unique=index.unique)

    return bootstrap_metadata


def upgrade() -> None:
    """Create the baseline schema expected by later incremental revisions."""
    bind = op.get_bind()
    _build_bootstrap_metadata().create_all(bind=bind, checkfirst=True)

    # Alembic creates alembic_version(version_num VARCHAR(32)) before any migration
    # runs.  Widen it so long revision IDs (> 32 chars) can be stamped.
    try:
        bind.execute(
            sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        )
    except Exception:  # noqa: BLE001
        pass


def downgrade() -> None:
    """Drop the bootstrap tables in reverse dependency order."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    bootstrap_metadata = _build_bootstrap_metadata()

    for table in reversed(bootstrap_metadata.sorted_tables):
        if table.name in existing_tables:
            table.drop(bind=bind, checkfirst=True)
