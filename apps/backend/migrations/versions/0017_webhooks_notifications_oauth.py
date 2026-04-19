"""Add webhooks, notifications, and oauth user fields

Revision ID: fecdb2050a32
Revises: a3b4c5d6e7fc
Create Date: 2026-03-08 00:39:39.615436

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fecdb2050a32"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — fully idempotent for DBs partially created before Alembic."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    def _cols(t):
        return {c["name"] for c in insp.get_columns(t)} if t in tables else set()

    def _idxs(t):
        return {i["name"] for i in insp.get_indexes(t)} if t in tables else set()

    # ── New tables ──────────────────────────────────────────────────────────

    if "credentials" not in tables:
        op.create_table(
            "credentials",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("target_entity_id", sa.Integer(), nullable=True),
            sa.Column("target_entity_type", sa.String(), nullable=True),
            sa.Column("credential_type", sa.String(), nullable=False),
            sa.Column("encrypted_value", sa.Text(), nullable=False),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "listener_events" not in tables:
        op.create_table(
            "listener_events",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("service_type", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("properties_json", sa.Text(), nullable=True),
            sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "ix_listener_events_seen_at" not in _idxs("listener_events"):
        op.create_index("ix_listener_events_seen_at", "listener_events", ["seen_at"], unique=False)

    if "notification_sinks" not in tables:
        op.create_table(
            "notification_sinks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("provider_type", sa.String(), nullable=False),
            sa.Column("provider_config", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "telemetry_timeseries" not in tables:
        op.create_table(
            "telemetry_timeseries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=False),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "webhook_rules" not in tables:
        op.create_table(
            "webhook_rules",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("target_url", sa.String(), nullable=False),
            sa.Column("secret", sa.String(), nullable=True),
            sa.Column("topics", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    if "integration_configs" not in tables:
        op.create_table(
            "integration_configs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("config_url", sa.String(), nullable=False),
            sa.Column("credential_id", sa.Integer(), nullable=True),
            sa.Column("cluster_name", sa.String(), nullable=True),
            sa.Column("auto_sync", sa.Boolean(), nullable=False),
            sa.Column("sync_interval_s", sa.Integer(), nullable=False),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_sync_status", sa.String(), nullable=True),
            sa.Column("extra_config", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["credential_id"], ["credentials.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "notification_routes" not in tables:
        op.create_table(
            "notification_routes",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("sink_id", sa.Integer(), nullable=False),
            sa.Column("alert_severity", sa.String(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["sink_id"], ["notification_sinks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "user_invites" not in tables:
        op.create_table(
            "user_invites",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("token", sa.Text(), nullable=False),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("invited_by", sa.Integer(), nullable=False),
            sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("email_sent_at", sa.String(), nullable=True),
            sa.Column("email_status", sa.String(), nullable=False),
            sa.Column("email_error", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )

    if "user_sessions" not in tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("jwt_token_hash", sa.Text(), nullable=False),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    # ── app_settings columns ─────────────────────────────────────────────────

    _as = _cols("app_settings")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    _as_new = [
        ("show_header_widgets", sa.Boolean(), False, sa.text("'1'")),
        ("show_time_widget", sa.Boolean(), False, sa.text("'1'")),
        ("show_weather_widget", sa.Boolean(), False, sa.text("'1'")),
        ("weather_location", sa.String(), False, sa.text("'Phoenix, AZ'")),
        ("registration_open", sa.Boolean(), False, sa.text("'1'")),
        ("rate_limit_profile", sa.String(), False, sa.text("'normal'")),
        ("dev_mode", sa.Boolean(), False, sa.text("'0'")),
        ("audit_log_retention_days", sa.Integer(), False, sa.text("'90'")),
        ("audit_log_hide_ip", sa.Boolean(), False, sa.text("'0'")),
        ("login_bg_path", sa.Text(), True, None),
        ("language", sa.String(), False, sa.text("'en'")),
        ("discovery_mode", sa.String(), False, sa.text("'safe'")),
        ("docker_discovery_enabled", sa.Boolean(), False, sa.text("'0'")),
        ("docker_socket_path", sa.String(), False, sa.text("'/var/run/docker.sock'")),
        ("docker_sync_interval_minutes", sa.Integer(), False, sa.text("'5'")),
        ("graph_default_layout", sa.String(), False, sa.text("'dagre'")),
        ("cve_sync_enabled", sa.Boolean(), False, sa.text("'0'")),
        ("cve_sync_interval_hours", sa.Integer(), False, sa.text("'24'")),
        ("cve_last_sync_at", sa.String(), True, None),
        ("realtime_notifications_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("realtime_transport", sa.String(), False, sa.text("'auto'")),
        ("listener_enabled", sa.Boolean(), False, sa.text("'0'")),
        ("prober_interval_minutes", sa.Integer(), False, sa.text("'15'")),
        ("deep_dive_max_parallel", sa.Integer(), False, sa.text("'5'")),
        ("scan_aggressiveness", sa.String(), False, sa.text("'normal'")),
        ("mdns_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("ssdp_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("arp_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("tcp_probe_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("self_cluster_enabled", sa.Boolean(), False, sa.text("'0'")),
        ("concurrent_sessions", sa.Integer(), False, sa.text("'5'")),
        ("login_lockout_attempts", sa.Integer(), False, sa.text("'5'")),
        ("login_lockout_minutes", sa.Integer(), False, sa.text("'15'")),
        ("invite_expiry_days", sa.Integer(), False, sa.text("'7'")),
        ("masquerade_enabled", sa.Boolean(), False, sa.text("'1'")),
        ("smtp_enabled", sa.Boolean(), False, sa.text("'0'")),
        ("smtp_host", sa.String(), False, sa.text("''")),
        ("smtp_port", sa.Integer(), False, sa.text("'587'")),
        ("smtp_username", sa.String(), False, sa.text("''")),
        ("smtp_password_enc", sa.Text(), True, None),
        ("smtp_from_email", sa.String(), False, sa.text("''")),
        ("smtp_from_name", sa.String(), False, sa.text("'Circuit Breaker'")),
        ("smtp_tls", sa.Boolean(), False, sa.text("'1'")),
        ("smtp_last_test_at", sa.String(), True, None),
        ("smtp_last_test_status", sa.String(), True, None),
        ("vault_key", sa.Text(), True, None),
        ("vault_key_hash", sa.Text(), True, None),
        ("vault_key_rotation_days", sa.Integer(), False, sa.text("'90'")),
        ("vault_key_rotated_at", sa.DateTime(timezone=True), True, None),
        ("db_backup_retention_days", sa.Integer(), False, sa.text("'30'")),
        ("oauth_providers", sa.Text(), True, None),
        ("oidc_providers", sa.Text(), True, None),
        ("session_timeout_hours", sa.Integer(), True, None),
    ]
    for col_name, col_type, nullable, server_default in _as_new:
        if col_name not in _as:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("app_settings", sa.Column(col_name, col_type, **col_kwargs))

    # ── compute_networks ─────────────────────────────────────────────────────

    _cn = _cols("compute_networks")
    for col_name in ("connection_type", "bandwidth_mbps"):
        if col_name not in _cn:
            col_type = sa.String() if col_name == "connection_type" else sa.Integer()
            op.add_column("compute_networks", sa.Column(col_name, col_type, nullable=True))

    # ── compute_units ────────────────────────────────────────────────────────

    _cu = _cols("compute_units")
    _cu_new = [
        ("download_speed_mbps", sa.Integer()),
        ("upload_speed_mbps", sa.Integer()),
        ("status_override", sa.String()),
        ("proxmox_vmid", sa.Integer()),
        ("proxmox_type", sa.String()),
        ("proxmox_config", sa.Text()),
        ("proxmox_status", sa.Text()),
        ("integration_config_id", sa.Integer()),
    ]
    for col_name, col_type in _cu_new:
        if col_name not in _cu:
            op.add_column("compute_units", sa.Column(col_name, col_type, nullable=True))

    for col_name in ("source", "discovered_at", "mac_address", "last_seen"):
        if col_name in _cols("compute_units"):
            try:
                op.drop_column("compute_units", col_name)
            except Exception:
                pass

    # ── discovery_profiles ───────────────────────────────────────────────────

    _dp = _cols("discovery_profiles")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    _dp_new = [
        ("vlan_ids", sa.String(), True, None),
        ("docker_network_types", sa.String(), False, sa.text("''")),
        ("docker_port_scan", sa.Integer(), False, sa.text("'0'")),
        ("docker_socket_path", sa.String(), False, sa.text("'/var/run/docker.sock'")),
    ]
    for col_name, col_type, nullable, server_default in _dp_new:
        if col_name not in _dp:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("discovery_profiles", sa.Column(col_name, col_type, **col_kwargs))

    # ── external_node_networks ───────────────────────────────────────────────

    _enn = _cols("external_node_networks")
    for col_name in ("connection_type", "bandwidth_mbps"):
        if col_name not in _enn:
            col_type = sa.String() if col_name == "connection_type" else sa.Integer()
            op.add_column("external_node_networks", sa.Column(col_name, col_type, nullable=True))

    # ── hardware ─────────────────────────────────────────────────────────────

    _hw = _cols("hardware")
    for col_name, col_type in [
        ("custom_icon", sa.String()),
        ("status_override", sa.String()),
        ("proxmox_node_name", sa.String()),
        ("integration_config_id", sa.Integer()),
    ]:
        if col_name not in _hw:
            op.add_column("hardware", sa.Column(col_name, col_type, nullable=True))

    if "idx_hardware_mac" in _idxs("hardware"):
        try:
            op.drop_index("idx_hardware_mac", table_name="hardware")
        except Exception:
            pass

    # ── hardware_cluster_members ─────────────────────────────────────────────

    _hcm = _cols("hardware_cluster_members")
    if "member_type" not in _hcm:
        op.add_column(
            "hardware_cluster_members",
            sa.Column(
                "member_type", sa.String(), nullable=False, server_default=sa.text("'hardware'")
            ),
        )
    if "service_id" not in _hcm:
        op.add_column(
            "hardware_cluster_members", sa.Column("service_id", sa.Integer(), nullable=True)
        )

    # ── hardware_clusters ────────────────────────────────────────────────────

    _hc = _cols("hardware_clusters")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("icon_slug", sa.String(), True, None),
        ("type", sa.String(), False, sa.text("'generic'")),
        ("integration_config_id", sa.Integer(), True, None),
    ]:
        if col_name not in _hc:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("hardware_clusters", sa.Column(col_name, col_type, **col_kwargs))

    # ── hardware_networks ────────────────────────────────────────────────────

    _hn = _cols("hardware_networks")
    for col_name in ("connection_type", "bandwidth_mbps"):
        if col_name not in _hn:
            col_type = sa.String() if col_name == "connection_type" else sa.Integer()
            op.add_column("hardware_networks", sa.Column(col_name, col_type, nullable=True))

    # ── logs ─────────────────────────────────────────────────────────────────

    _lg = _cols("logs")
    for col_name, col_type in [
        ("session_id", sa.Integer()),
        ("role_at_time", sa.String()),
        ("previous_hash", sa.String()),
        ("log_hash", sa.String()),
    ]:
        if col_name not in _lg:
            op.add_column("logs", sa.Column(col_name, col_type, nullable=True))

    if "ix_logs_log_hash" not in _idxs("logs"):
        try:
            op.create_index("ix_logs_log_hash", "logs", ["log_hash"], unique=True)
        except Exception:
            pass

    # ── networks ─────────────────────────────────────────────────────────────

    _nw = _cols("networks")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("docker_network_id", sa.String(), True, None),
        ("docker_driver", sa.String(), True, None),
        ("is_docker_network", sa.Boolean(), False, sa.text("'0'")),
    ]:
        if col_name not in _nw:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("networks", sa.Column(col_name, col_type, **col_kwargs))

    # ── scan_jobs ────────────────────────────────────────────────────────────

    _sj = _cols("scan_jobs")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("vlan_ids", sa.String(), True, None),
        ("network_ids", sa.String(), True, None),
        ("source_type", sa.String(), False, sa.text("'manual'")),
    ]:
        if col_name not in _sj:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("scan_jobs", sa.Column(col_name, col_type, **col_kwargs))

    _sj_idxs = _idxs("scan_jobs")
    if "ix_scan_jobs_created_at" not in _sj_idxs:
        op.create_index("ix_scan_jobs_created_at", "scan_jobs", ["created_at"], unique=False)
    if "ix_scan_jobs_status" not in _sj_idxs:
        op.create_index("ix_scan_jobs_status", "scan_jobs", ["status"], unique=False)

    # ── scan_results ─────────────────────────────────────────────────────────

    _sr = _cols("scan_results")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("vlan_id", sa.Integer(), True, None),
        ("network_id", sa.Integer(), True, None),
        ("banner", sa.Text(), True, None),
        ("os_accuracy", sa.Integer(), True, None),
        ("source_type", sa.String(), False, sa.text("'manual'")),
    ]:
        if col_name not in _sr:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("scan_results", sa.Column(col_name, col_type, **col_kwargs))

    _sr_idxs = _idxs("scan_results")
    for old_idx in ("idx_scan_results_ip", "idx_scan_results_job", "idx_scan_results_merge"):
        if old_idx in _sr_idxs:
            try:
                op.drop_index(old_idx, table_name="scan_results")
            except Exception:
                pass
    for idx_name, col in [
        ("ix_scan_results_created_at", "created_at"),
        ("ix_scan_results_scan_job_id", "scan_job_id"),
        ("ix_scan_results_state", "state"),
    ]:
        if idx_name not in _idxs("scan_results"):
            op.create_index(idx_name, "scan_results", [col], unique=False)

    # ── service_* edge tables ────────────────────────────────────────────────

    for tbl in (
        "service_dependencies",
        "service_external_nodes",
        "service_misc",
        "service_storage",
    ):
        _t = _cols(tbl)
        for col_name in ("connection_type", "bandwidth_mbps"):
            if col_name not in _t:
                col_type = sa.String() if col_name == "connection_type" else sa.Integer()
                op.add_column(tbl, sa.Column(col_name, col_type, nullable=True))

    # ── services ─────────────────────────────────────────────────────────────

    _sv = _cols("services")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("custom_icon", sa.String(), True, None),
        ("docker_container_id", sa.String(), True, None),
        ("docker_image", sa.String(), True, None),
        ("docker_labels", sa.Text(), True, None),
        ("is_docker_container", sa.Boolean(), False, sa.text("'0'")),
    ]:
        if col_name not in _sv:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("services", sa.Column(col_name, col_type, **col_kwargs))

    for col_name in ("source", "service_version", "banner"):
        if col_name in _cols("services"):
            try:
                op.drop_column("services", col_name)
            except Exception:
                pass

    # ── storage ──────────────────────────────────────────────────────────────

    _st = _cols("storage")
    for col_name, col_type in [
        ("integration_config_id", sa.Integer()),
        ("proxmox_storage_name", sa.String()),
    ]:
        if col_name not in _st:
            op.add_column("storage", sa.Column(col_name, col_type, nullable=True))

    # ── user_icons ───────────────────────────────────────────────────────────

    _ui = _cols("user_icons")
    for col_name, col_type, nullable in [
        ("user_id", sa.Integer(), True),
        ("filename", sa.String(), True),
        ("original_name", sa.String(), True),
        ("mime_type", sa.String(), True),
        ("size_bytes", sa.Integer(), True),
        ("hash", sa.String(), True),
        ("uploaded_at", sa.DateTime(timezone=True), True),
    ]:
        if col_name not in _ui:
            op.add_column("user_icons", sa.Column(col_name, col_type, nullable=nullable))

    # ── users ────────────────────────────────────────────────────────────────

    _us = _cols("users")
    # 4-tuple: (col_name, col_type, nullable, server_default)
    for col_name, col_type, nullable, server_default in [
        ("hashed_password", sa.Text(), False, sa.text("''")),
        ("language", sa.Text(), False, sa.text("'en'")),
        ("is_active", sa.Boolean(), False, sa.text("'1'")),
        ("is_superuser", sa.Boolean(), False, sa.text("'0'")),
        ("updated_at", sa.DateTime(timezone=True), True, None),
        ("role", sa.String(), False, sa.text("'viewer'")),
        ("invited_by", sa.Integer(), True, None),
        ("login_attempts", sa.Integer(), False, sa.text("'0'")),
        ("locked_until", sa.DateTime(timezone=True), True, None),
        ("masquerade_target", sa.Integer(), True, None),
        ("force_password_change", sa.Boolean(), False, sa.text("'0'")),
        ("provider", sa.String(), False, sa.text("'local'")),
        ("oauth_tokens", sa.Text(), True, None),
    ]:
        if col_name not in _us:
            col_kwargs: dict = {"nullable": nullable}
            if server_default is not None:
                col_kwargs["server_default"] = server_default
            op.add_column("users", sa.Column(col_name, col_type, **col_kwargs))

    if "password_hash" in _cols("users"):
        try:
            op.drop_column("users", "password_hash")
        except Exception:
            pass


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("users", sa.Column("password_hash", sa.TEXT(), nullable=False))
    op.drop_constraint(None, "users", type_="foreignkey")
    op.drop_constraint(None, "users", type_="foreignkey")
    op.drop_column("users", "oauth_tokens")
    op.drop_column("users", "provider")
    op.drop_column("users", "force_password_change")
    op.drop_column("users", "masquerade_target")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "login_attempts")
    op.drop_column("users", "invited_by")
    op.drop_column("users", "role")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_superuser")
    op.drop_column("users", "is_active")
    op.drop_column("users", "language")
    op.drop_column("users", "hashed_password")
    op.drop_constraint(None, "user_icons", type_="unique")
    op.drop_column("user_icons", "uploaded_at")
    op.drop_column("user_icons", "hash")
    op.drop_column("user_icons", "size_bytes")
    op.drop_column("user_icons", "mime_type")
    op.drop_column("user_icons", "original_name")
    op.drop_column("user_icons", "filename")
    op.drop_column("user_icons", "user_id")
    op.drop_constraint(None, "storage", type_="foreignkey")
    op.drop_column("storage", "proxmox_storage_name")
    op.drop_column("storage", "integration_config_id")
    op.add_column("services", sa.Column("banner", sa.TEXT(), nullable=True))
    op.add_column("services", sa.Column("service_version", sa.TEXT(), nullable=True))
    op.add_column(
        "services",
        sa.Column("source", sa.TEXT(), server_default=sa.text("'manual'"), nullable=True),
    )
    op.drop_constraint(None, "services", type_="unique")
    op.alter_column(
        "services",
        "ip_conflict_json",
        existing_type=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'[]'"),
    )
    op.alter_column(
        "services",
        "ip_conflict",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "services",
        "ip_mode",
        existing_type=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'explicit'"),
    )
    op.drop_column("services", "is_docker_container")
    op.drop_column("services", "docker_labels")
    op.drop_column("services", "docker_image")
    op.drop_column("services", "docker_container_id")
    op.drop_column("services", "custom_icon")
    op.drop_column("service_storage", "bandwidth_mbps")
    op.drop_column("service_storage", "connection_type")
    op.drop_column("service_misc", "bandwidth_mbps")
    op.drop_column("service_misc", "connection_type")
    op.drop_column("service_external_nodes", "bandwidth_mbps")
    op.drop_column("service_external_nodes", "connection_type")
    op.drop_column("service_dependencies", "bandwidth_mbps")
    op.drop_column("service_dependencies", "connection_type")
    op.drop_constraint(None, "scan_results", type_="foreignkey")
    op.drop_index(op.f("ix_scan_results_state"), table_name="scan_results")
    op.drop_index(op.f("ix_scan_results_scan_job_id"), table_name="scan_results")
    op.drop_index(op.f("ix_scan_results_created_at"), table_name="scan_results")
    op.create_index(op.f("idx_scan_results_merge"), "scan_results", ["merge_status"], unique=False)
    op.create_index(op.f("idx_scan_results_job"), "scan_results", ["scan_job_id"], unique=False)
    op.create_index(op.f("idx_scan_results_ip"), "scan_results", ["ip_address"], unique=False)
    op.alter_column(
        "scan_results",
        "conflicts_json",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.drop_column("scan_results", "source_type")
    op.drop_column("scan_results", "os_accuracy")
    op.drop_column("scan_results", "banner")
    op.drop_column("scan_results", "network_id")
    op.drop_column("scan_results", "vlan_id")
    op.drop_index(op.f("ix_scan_jobs_status"), table_name="scan_jobs")
    op.drop_index(op.f("ix_scan_jobs_created_at"), table_name="scan_jobs")
    op.alter_column(
        "scan_jobs",
        "progress_message",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column(
        "scan_jobs",
        "progress_phase",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'queued'"),
    )
    op.alter_column("scan_jobs", "target_cidr", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_column("scan_jobs", "source_type")
    op.drop_column("scan_jobs", "network_ids")
    op.drop_column("scan_jobs", "vlan_ids")
    op.drop_constraint(None, "networks", type_="unique")
    op.drop_column("networks", "is_docker_network")
    op.drop_column("networks", "docker_driver")
    op.drop_column("networks", "docker_network_id")
    op.drop_constraint(None, "logs", type_="foreignkey")
    op.drop_index(op.f("ix_logs_log_hash"), table_name="logs")
    op.alter_column(
        "logs",
        "severity",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=False,
        existing_server_default=sa.text("'info'"),
    )
    op.alter_column(
        "logs", "entity_name", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True
    )
    op.alter_column(
        "logs",
        "actor_name",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=False,
        existing_server_default=sa.text("'admin'"),
    )
    op.alter_column(
        "logs", "created_at_utc", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True
    )
    op.drop_column("logs", "log_hash")
    op.drop_column("logs", "previous_hash")
    op.drop_column("logs", "role_at_time")
    op.drop_column("logs", "session_id")
    op.drop_column("hardware_networks", "bandwidth_mbps")
    op.drop_column("hardware_networks", "connection_type")
    op.drop_constraint(None, "hardware_clusters", type_="foreignkey")
    op.drop_column("hardware_clusters", "integration_config_id")
    op.drop_column("hardware_clusters", "type")
    op.drop_column("hardware_clusters", "icon_slug")
    op.drop_constraint(None, "hardware_cluster_members", type_="foreignkey")
    op.alter_column(
        "hardware_cluster_members", "hardware_id", existing_type=sa.INTEGER(), nullable=False
    )
    op.drop_column("hardware_cluster_members", "service_id")
    op.drop_column("hardware_cluster_members", "member_type")
    op.drop_constraint(None, "hardware", type_="foreignkey")
    op.create_index(
        op.f("idx_hardware_mac"),
        "hardware",
        ["mac_address"],
        unique=1,
        sqlite_where=sa.text("mac_address IS NOT NULL AND mac_address != ''"),
    )
    op.alter_column(
        "hardware",
        "software_platform",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
        existing_server_default=sa.text("(NULL)"),
    )
    op.alter_column(
        "hardware", "os_version", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True
    )
    op.alter_column(
        "hardware",
        "source",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
        existing_server_default=sa.text("'manual'"),
    )
    op.alter_column(
        "hardware",
        "discovered_at",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.alter_column(
        "hardware", "last_seen", existing_type=sa.String(), type_=sa.TEXT(), existing_nullable=True
    )
    op.alter_column(
        "hardware",
        "status",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
        existing_server_default=sa.text("'unknown'"),
    )
    op.alter_column(
        "hardware",
        "mac_address",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.alter_column(
        "hardware",
        "telemetry_last_polled",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.TIMESTAMP(),
        existing_nullable=True,
    )
    op.alter_column(
        "hardware",
        "telemetry_status",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
        existing_server_default=sa.text("'unknown'"),
    )
    op.alter_column(
        "hardware",
        "model_catalog_key",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.alter_column(
        "hardware",
        "vendor_catalog_key",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
    )
    op.drop_column("hardware", "integration_config_id")
    op.drop_column("hardware", "proxmox_node_name")
    op.drop_column("hardware", "status_override")
    op.drop_column("hardware", "custom_icon")
    op.drop_column("external_node_networks", "bandwidth_mbps")
    op.drop_column("external_node_networks", "connection_type")
    op.alter_column(
        "docs",
        "icon",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column(
        "docs",
        "pinned",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "docs",
        "category",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column("discovery_profiles", "cidr", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_column("discovery_profiles", "docker_socket_path")
    op.drop_column("discovery_profiles", "docker_port_scan")
    op.drop_column("discovery_profiles", "docker_network_types")
    op.drop_column("discovery_profiles", "vlan_ids")
    op.add_column("compute_units", sa.Column("last_seen", sa.TEXT(), nullable=True))
    op.add_column("compute_units", sa.Column("mac_address", sa.TEXT(), nullable=True))
    op.add_column("compute_units", sa.Column("discovered_at", sa.TEXT(), nullable=True))
    op.add_column(
        "compute_units",
        sa.Column("source", sa.TEXT(), server_default=sa.text("'manual'"), nullable=True),
    )
    op.drop_constraint(None, "compute_units", type_="foreignkey")
    op.alter_column(
        "compute_units",
        "status",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=True,
        existing_server_default=sa.text("'unknown'"),
    )
    op.drop_column("compute_units", "integration_config_id")
    op.drop_column("compute_units", "proxmox_status")
    op.drop_column("compute_units", "proxmox_config")
    op.drop_column("compute_units", "proxmox_type")
    op.drop_column("compute_units", "proxmox_vmid")
    op.drop_column("compute_units", "status_override")
    op.drop_column("compute_units", "upload_speed_mbps")
    op.drop_column("compute_units", "download_speed_mbps")
    op.drop_column("compute_networks", "bandwidth_mbps")
    op.drop_column("compute_networks", "connection_type")
    op.alter_column(
        "app_settings",
        "ui_font_size",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'medium'"),
    )
    op.alter_column(
        "app_settings",
        "ui_font",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'inter'"),
    )
    op.alter_column(
        "app_settings",
        "scan_ack_accepted",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "app_settings",
        "discovery_retention_days",
        existing_type=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("(30)"),
    )
    op.alter_column(
        "app_settings",
        "discovery_http_probe",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("1"),
    )
    op.alter_column(
        "app_settings",
        "discovery_schedule_cron",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column(
        "app_settings",
        "discovery_snmp_community",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column(
        "app_settings",
        "discovery_nmap_args",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("'-sV -O --open -T4'"),
    )
    op.alter_column(
        "app_settings",
        "discovery_default_cidr",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        nullable=True,
        existing_server_default=sa.text("('')"),
    )
    op.alter_column(
        "app_settings",
        "discovery_auto_merge",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "app_settings",
        "discovery_enabled",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )
    op.alter_column(
        "app_settings",
        "timezone",
        existing_type=sa.String(),
        type_=sa.TEXT(),
        existing_nullable=False,
        existing_server_default=sa.text("'UTC'"),
    )
    op.alter_column(
        "app_settings",
        "show_experimental_features",
        existing_type=sa.Boolean(),
        type_=sa.INTEGER(),
        existing_nullable=False,
    )
    op.drop_column("app_settings", "db_backup_retention_days")
    op.drop_column("app_settings", "vault_key_rotated_at")
    op.drop_column("app_settings", "vault_key_rotation_days")
    op.drop_column("app_settings", "vault_key_hash")
    op.drop_column("app_settings", "vault_key")
    op.drop_column("app_settings", "smtp_last_test_status")
    op.drop_column("app_settings", "smtp_last_test_at")
    op.drop_column("app_settings", "smtp_tls")
    op.drop_column("app_settings", "smtp_from_name")
    op.drop_column("app_settings", "smtp_from_email")
    op.drop_column("app_settings", "smtp_password_enc")
    op.drop_column("app_settings", "smtp_username")
    op.drop_column("app_settings", "smtp_port")
    op.drop_column("app_settings", "smtp_host")
    op.drop_column("app_settings", "smtp_enabled")
    op.drop_column("app_settings", "masquerade_enabled")
    op.drop_column("app_settings", "invite_expiry_days")
    op.drop_column("app_settings", "login_lockout_minutes")
    op.drop_column("app_settings", "login_lockout_attempts")
    op.drop_column("app_settings", "concurrent_sessions")
    op.drop_column("app_settings", "self_cluster_enabled")
    op.drop_column("app_settings", "tcp_probe_enabled")
    op.drop_column("app_settings", "arp_enabled")
    op.drop_column("app_settings", "ssdp_enabled")
    op.drop_column("app_settings", "mdns_enabled")
    op.drop_column("app_settings", "scan_aggressiveness")
    op.drop_column("app_settings", "deep_dive_max_parallel")
    op.drop_column("app_settings", "prober_interval_minutes")
    op.drop_column("app_settings", "listener_enabled")
    op.drop_column("app_settings", "realtime_transport")
    op.drop_column("app_settings", "realtime_notifications_enabled")
    op.drop_column("app_settings", "cve_last_sync_at")
    op.drop_column("app_settings", "cve_sync_interval_hours")
    op.drop_column("app_settings", "cve_sync_enabled")
    op.drop_column("app_settings", "graph_default_layout")
    op.drop_column("app_settings", "docker_sync_interval_minutes")
    op.drop_column("app_settings", "docker_socket_path")
    op.drop_column("app_settings", "docker_discovery_enabled")
    op.drop_column("app_settings", "discovery_mode")
    op.drop_column("app_settings", "language")
    op.drop_column("app_settings", "login_bg_path")
    op.drop_column("app_settings", "audit_log_hide_ip")
    op.drop_column("app_settings", "audit_log_retention_days")
    op.drop_column("app_settings", "dev_mode")
    op.drop_column("app_settings", "rate_limit_profile")
    op.drop_column("app_settings", "registration_open")
    op.drop_column("app_settings", "weather_location")
    op.drop_column("app_settings", "show_weather_widget")
    op.drop_column("app_settings", "show_time_widget")
    op.drop_column("app_settings", "show_header_widgets")
    op.drop_table("user_sessions")
    op.drop_table("user_invites")
    op.drop_table("notification_routes")
    op.drop_table("integration_configs")
    op.drop_table("webhook_rules")
    op.drop_table("telemetry_timeseries")
    op.drop_table("notification_sinks")
    op.drop_index(op.f("ix_listener_events_seen_at"), table_name="listener_events")
    op.drop_table("listener_events")
    op.drop_table("credentials")
    # ### end Alembic commands ###
