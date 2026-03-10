"""v0.2.0 — PostgreSQL JSONB columns, Teams, and Explicit Topologies

Revision ID: 0026_pg_jsonb_teams_topologies
Revises: 0025_status_pages
Create Date: 2026-03-09

Changes:
  - Convert ~25 Text-as-JSON columns to JSONB (idempotent DO $$ guards)
  - Add GIN indexes on hardware.telemetry_config & telemetry_data
  - Create teams / team_members tables and seed Default Team (id=1)
  - Add team_id FK to 8 entity tables; back-fill team_id=1 for existing rows
  - Create topologies / topology_nodes / topology_edges tables
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026_pg_jsonb_teams_topologies"
down_revision = "0025_status_pages"
branch_labels = None
depends_on = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JSONB_CASTS: list[tuple[str, str]] = [
    # (table, column)
    ("hardware", "telemetry_config"),
    ("hardware", "telemetry_data"),
    ("hardware", "wifi_standards"),
    ("hardware", "wifi_bands"),
    ("hardware", "port_map_json"),
    ("services", "ip_conflict_json"),
    ("services", "ports_json"),
    ("services", "docker_labels"),
    ("compute_units", "proxmox_config"),
    ("compute_units", "proxmox_status"),
    ("hardware_monitors", "probe_methods"),
    ("integration_configs", "extra_config"),
    ("graph_layouts", "layout_data"),
    ("webhook_rules", "events_enabled"),
    ("webhook_rules", "headers_json"),
    ("notification_sinks", "provider_config"),
    ("status_groups", "nodes"),
    ("status_groups", "services"),
    ("status_history", "metrics"),
    ("status_history", "raw_telemetry"),
    ("scan_results", "open_ports_json"),
    ("scan_results", "snmp_interfaces_json"),
    ("scan_results", "snmp_storage_json"),
    ("scan_results", "conflicts_json"),
    ("listener_events", "properties_json"),
    ("app_settings", "map_default_filters"),
    ("app_settings", "accent_colors"),
    ("app_settings", "custom_colors"),
    ("app_settings", "oauth_providers"),
    ("app_settings", "oidc_providers"),
]

# Tables that receive a nullable team_id FK (back-filled to 1)
_TEAM_FK_TABLES: list[str] = [
    "hardware",
    "services",
    "networks",
    "hardware_clusters",
    "external_nodes",
    "scan_jobs",
    "live_metrics",
    "integration_configs",
]


def _cast_column_to_jsonb(bind, table: str, column: str) -> None:
    """CAST a text column to jsonb if it exists and isn't already jsonb."""
    try:
        bind.execute(
            sa.text(
                f"""
                DO $$
                BEGIN
                    -- Skip if column is already jsonb
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}'
                          AND column_name = '{column}'
                          AND data_type != 'jsonb'
                    ) THEN
                        ALTER TABLE {table}
                            ALTER COLUMN {column} TYPE jsonb
                            USING COALESCE(
                                CASE
                                    WHEN {column} IS NULL THEN NULL
                                    WHEN TRIM({column}) = '' THEN NULL
                                    ELSE {column}::jsonb
                                END,
                                NULL
                            );
                    END IF;
                EXCEPTION WHEN others THEN
                    RAISE WARNING 'Could not cast {table}.{column} to jsonb: %', SQLERRM;
                END $$;
                """
            )
        )
    except Exception as exc:  # noqa: BLE001
        import warnings

        warnings.warn(f"JSONB cast failed for {table}.{column}: {exc}", stacklevel=2)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing_tables = set(insp.get_table_names())

    # ── 1. JSONB column casts ─────────────────────────────────────────────
    for table, column in _JSONB_CASTS:
        if table in existing_tables:
            _cast_column_to_jsonb(bind, table, column)

    # ── 2. GIN indexes for telemetry columns ──────────────────────────────
    if "hardware" in existing_tables:
        bind.execute(
            sa.text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hw_telemetry_data_gin "
                "ON hardware USING GIN(telemetry_data) WHERE telemetry_data IS NOT NULL;"
            )
        )
        bind.execute(
            sa.text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_hw_telemetry_cfg_gin "
                "ON hardware USING GIN(telemetry_config) WHERE telemetry_config IS NOT NULL;"
            )
        )

    # ── 3. Teams tables ───────────────────────────────────────────────────
    if "teams" not in existing_tables:
        op.create_table(
            "teams",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    if "team_members" not in existing_tables:
        op.create_table(
            "team_members",
            sa.Column("team_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("team_role", sa.String(20), nullable=False, server_default="member"),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("team_id", "user_id"),
        )

    # Seed Default Team (id=1) — idempotent
    bind.execute(
        sa.text(
            "INSERT INTO teams (id, name, created_at, updated_at) "
            "VALUES (1, 'Default Team', now(), now()) "
            "ON CONFLICT (id) DO NOTHING;"
        )
    )
    # Ensure the sequence is past id=1 so next auto-increment doesn't collide
    bind.execute(
        sa.text("SELECT setval('teams_id_seq', GREATEST(1, (SELECT MAX(id) FROM teams)));")
    )

    # ── 4. team_id FK columns on entity tables ────────────────────────────
    for tbl in _TEAM_FK_TABLES:
        if tbl not in existing_tables:
            continue
        existing_cols = {c["name"] for c in insp.get_columns(tbl)}
        if "team_id" not in existing_cols:
            bind.execute(
                sa.text(
                    f"ALTER TABLE {tbl} "
                    f"ADD COLUMN team_id INTEGER REFERENCES teams(id) ON DELETE SET NULL;"
                )
            )
        # Back-fill all existing rows → Default Team
        bind.execute(sa.text(f"UPDATE {tbl} SET team_id = 1 WHERE team_id IS NULL;"))
        # Index (IF NOT EXISTS guard)
        bind.execute(sa.text(f"CREATE INDEX IF NOT EXISTS idx_{tbl}_team_id ON {tbl}(team_id);"))

    # ── 5. Topology tables ────────────────────────────────────────────────
    if "topologies" not in existing_tables:
        op.create_table(
            "topologies",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("team_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_topologies_team_id", "topologies", ["team_id"])

    if "topology_nodes" not in existing_tables:
        op.create_table(
            "topology_nodes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("topology_id", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(50), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("x", sa.Float(), nullable=True),
            sa.Column("y", sa.Float(), nullable=True),
            sa.Column("size", sa.Float(), nullable=True),
            sa.Column("extra", JSONB, nullable=True),
            sa.ForeignKeyConstraint(["topology_id"], ["topologies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_topology_nodes_topology_id", "topology_nodes", ["topology_id"])

    if "topology_edges" not in existing_tables:
        op.create_table(
            "topology_edges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("topology_id", sa.Integer(), nullable=False),
            sa.Column("source_node_id", sa.Integer(), nullable=False),
            sa.Column("target_node_id", sa.Integer(), nullable=False),
            sa.Column("edge_type", sa.String(50), nullable=True, server_default="ethernet"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["topology_id"], ["topologies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_node_id"], ["topology_nodes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_node_id"], ["topology_nodes.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_topology_edges_topology_id", "topology_edges", ["topology_id"])

    # Migrate existing GraphLayout → default Topology for team 1
    bind.execute(
        sa.text(
            """
            INSERT INTO topologies (team_id, name, is_default, created_at, updated_at)
            SELECT 1, name, true, now(), now()
            FROM graph_layouts
            WHERE context = 'topology' OR context IS NULL
            LIMIT 1
            ON CONFLICT DO NOTHING;
            """
        )
    )


def downgrade() -> None:
    # Drop topology tables
    op.drop_index("ix_topology_edges_topology_id", table_name="topology_edges")
    op.drop_table("topology_edges")
    op.drop_index("ix_topology_nodes_topology_id", table_name="topology_nodes")
    op.drop_table("topology_nodes")
    op.drop_index("ix_topologies_team_id", table_name="topologies")
    op.drop_table("topologies")

    # Drop team_id columns
    bind = op.get_bind()
    for tbl in _TEAM_FK_TABLES:
        try:
            bind.execute(sa.text(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS team_id;"))
        except Exception:  # noqa: BLE001
            pass

    # Drop team tables
    op.drop_table("team_members")
    op.drop_table("teams")

    # Note: JSONB → TEXT downgrade is intentionally omitted (lossy and generally not needed).
    # To rollback JSONB columns manually:
    #   ALTER TABLE hardware ALTER COLUMN telemetry_config TYPE text USING telemetry_config::text;
