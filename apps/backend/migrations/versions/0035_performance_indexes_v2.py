"""Compound performance indexes for topology queries and hot paths.

Revision ID: 0035_performance_indexes_v2
Revises: 0034_security_hardening
Create Date: 2026-03-11

Adds compound indexes that are critical for <50ms topology queries at 10k+ nodes.
All indexes are created with IF NOT EXISTS guards to be idempotent.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_performance_indexes_v2"
down_revision = "0034_security_hardening"
branch_labels = None
depends_on = None

_INDEXES: list[tuple[str, str, list[str]]] = [
    # hardware — topology filters
    ("ix_hw_team_role", "hardware", ["team_id", "role"]),
    ("ix_hw_team_ip", "hardware", ["team_id", "ip_address"]),
    ("ix_hw_team_last_seen", "hardware", ["team_id", "last_seen"]),
    ("ix_hw_environment_id", "hardware", ["environment_id"]),
    ("ix_hw_rack_id", "hardware", ["rack_id"]),
    # compute_units — parent lookups
    ("ix_cu_hardware_id", "compute_units", ["hardware_id"]),
    ("ix_cu_environment_id", "compute_units", ["environment_id"]),
    # services — parent lookups
    ("ix_svc_compute_id", "services", ["compute_id"]),
    ("ix_svc_hardware_id", "services", ["hardware_id"]),
    ("ix_svc_environment_id", "services", ["environment_id"]),
    # join tables — both FK columns for graph edge traversal
    ("ix_hn_hw_net", "hardware_networks", ["hardware_id", "network_id"]),
    ("ix_hn_net", "hardware_networks", ["network_id"]),
    ("ix_cn_cu_net", "compute_networks", ["compute_id", "network_id"]),
    ("ix_cn_net", "compute_networks", ["network_id"]),
    ("ix_hconn_source", "hardware_connections", ["source_hardware_id"]),
    ("ix_hconn_target", "hardware_connections", ["target_hardware_id"]),
    ("ix_hcm_cluster_hw", "hardware_cluster_members", ["cluster_id", "hardware_id"]),
    # polymorphic entity relations
    ("ix_etag_entity", "entity_tags", ["entity_type", "entity_id"]),
    ("ix_edoc_entity", "entity_docs", ["entity_type", "entity_id"]),
    # audit log — time-range + category filter
    ("ix_logs_ts_cat", "logs", ["timestamp", "category"]),
    # telemetry — entity + time-range lookups
    ("ix_tts_entity_ts", "telemetry_timeseries", ["entity_type", "entity_id", "ts"]),
    # networks — gateway lookups
    ("ix_net_gateway_hw", "networks", ["gateway_hardware_id"]),
    # service dependencies
    ("ix_sdep_svc", "service_dependencies", ["service_id"]),
    ("ix_sdep_dep", "service_dependencies", ["depends_on_id"]),
    # service-storage, service-misc
    ("ix_ss_svc", "service_storage", ["service_id"]),
    ("ix_sm_svc", "service_misc", ["service_id"]),
    # external node links
    ("ix_enn_ext", "external_node_networks", ["external_node_id"]),
    ("ix_sen_svc", "service_external_nodes", ["service_id"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    existing_indexes: set[str] = set()
    for table in existing_tables:
        try:
            for idx in insp.get_indexes(table):
                existing_indexes.add(idx["name"])
        except Exception:  # noqa: BLE001
            pass

    for name, table, cols in _INDEXES:
        if table not in existing_tables:
            continue
        if name in existing_indexes:
            continue
        table_cols = {c["name"] for c in insp.get_columns(table)}
        if not all(c in table_cols for c in cols):
            continue
        op.create_index(name, table, cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    existing_indexes: dict[str, str] = {}
    for table in existing_tables:
        try:
            for idx in insp.get_indexes(table):
                existing_indexes[idx["name"]] = table
        except Exception:  # noqa: BLE001
            pass

    for name, _table, _cols in reversed(_INDEXES):
        if name in existing_indexes:
            op.drop_index(name, table_name=existing_indexes[name])
