"""The single application settings row, the device-role catalog, and OOBE step state."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models._shared import _now
from app.db.session import Base

# ── App Settings ──────────────────────────────────────────────────────────────


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    theme: Mapped[str] = mapped_column(String, nullable=False, default="dark")
    default_environment: Mapped[str | None] = mapped_column(String)
    show_experimental_features: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    api_base_url: Mapped[str | None] = mapped_column(String)
    vendor_icon_mode: Mapped[str] = mapped_column(String, nullable=False, default="custom_files")
    environments: Mapped[str | None] = mapped_column(
        Text, default='["prod","staging","dev"]'
    )  # JSON array
    categories: Mapped[str | None] = mapped_column(Text, default="[]")  # JSON array
    locations: Mapped[str | None] = mapped_column(Text, default="[]")  # JSON array
    dock_order: Mapped[str | None] = mapped_column(Text)  # JSON array of path strings
    dock_hidden_items: Mapped[str | None] = mapped_column(Text)  # JSON array of hidden path strings
    show_page_hints: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_header_widgets: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_time_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_weather_widget: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weather_location: Mapped[str] = mapped_column(String, nullable=False, default="Phoenix, AZ")
    auth_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    registration_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_profile: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    jwt_secret: Mapped[str | None] = mapped_column(Text)
    client_hash_salt: Mapped[str | None] = mapped_column(Text)
    bootstrap_token_hash: Mapped[str | None] = mapped_column(Text)
    bootstrap_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bootstrap_token_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session_timeout_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    dev_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_log_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    audit_log_hide_ip: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Hash of the last audit-log row the retention purge deleted. The audit
    # chain links each row to its predecessor, so removing the oldest rows
    # orphans whatever row becomes first: its previous_hash names a row that no
    # longer exists, and verify_audit_chain — which seeds its walk from NULL,
    # the genesis value — reported "chain broken" on every install that lived
    # past its retention window. The purge records the tip it cut here and the
    # verifier seeds from it instead, so a purge stays verifiable while a
    # *deletion nobody recorded* still reads as tampering. Do not write this
    # from anywhere but services/log_purge.py: any other writer can forge an
    # arbitrary chain prefix by setting it. NULL means "chain starts at
    # genesis", i.e. a fresh install that has never been purged.
    #
    # Adding this column REQUIRES an Alembic revision, and shipping the model
    # without one is a total outage rather than a degraded audit feature:
    # get_or_create_settings does `db.get(AppSettings, 1)` — a full-entity
    # SELECT naming every column — and has call sites throughout the app,
    # core/security.py's session verification among them. A database missing
    # this column therefore fails *every authenticated request* with
    # UndefinedColumn, not merely the purge and the chain verifier.
    audit_chain_checkpoint_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    telemetry_hot_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telemetry_warm_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Branding
    app_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    favicon_path: Mapped[str | None] = mapped_column(Text)
    login_logo_path: Mapped[str | None] = mapped_column(Text)
    login_bg_path: Mapped[str | None] = mapped_column(Text)
    primary_color: Mapped[str] = mapped_column(String, nullable=False, default="#fe8019")
    accent_colors: Mapped[list | None] = mapped_column(
        JSONB, default=lambda: ["#fabd2f", "#b8bb26"]
    )  # JSONB as of v0.2.0
    # Advanced Theming
    theme_preset: Mapped[str] = mapped_column(String, nullable=False, default="gruvbox-dark")
    custom_colors: Mapped[dict | None] = mapped_column(
        JSONB
    )  # JSONB: {primary,secondary,accent1,accent2,background,surface}
    # External nodes
    show_external_nodes_on_map: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Timezone preference (IANA name, e.g. "America/Denver")
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    language: Mapped[str] = mapped_column(String, nullable=False, default="en")
    # Auto-Discovery settings
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_auto_merge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    discovery_default_cidr: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_nmap_args: Mapped[str] = mapped_column(
        String, nullable=False, default="-sV -O --open -T4"
    )
    discovery_snmp_community: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_schedule_cron: Mapped[str] = mapped_column(String, nullable=False, default="")
    discovery_http_probe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovery_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    scan_ack_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nmap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Safe discovery mode
    discovery_mode: Mapped[str] = mapped_column(String, nullable=False, default="safe")
    docker_discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    docker_socket_path: Mapped[str] = mapped_column(
        String, nullable=False, default="/var/run/docker.sock"
    )
    docker_sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # Phase 2 discovery-readiness: persisted user consent for LAN discovery.
    # Set only by the explicit toggle; the reconciler converges actual state
    # to this value, never the other way around.
    lan_discovery_desired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Slice 4 plan §3/§6 (Task 26 / M14): the fleet-wide hold on *agent-executed*
    # discovery, read by `discovery_admission.global_agent_discovery_paused` and
    # written by `POST /api/v1/discovery/pause`. Deliberately narrower
    # than `discovery_enabled`, which is the product's master discovery switch:
    # a second flag that also silenced the server's own crons would mean holding
    # an agent fleet stopped scanning the networks the server can see itself.
    # A pause withholds scheduling only — it deletes no profile, job or result.
    agent_discovery_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Domain (FQDN) configured via the OOBE Domain step or a later Settings edit.
    # None = no domain configured, instance is IP-only with a self-signed cert.
    fqdn: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    graph_default_layout: Mapped[str] = mapped_column(String, nullable=False, default="dagre")
    map_title: Mapped[str] = mapped_column(String, nullable=False, default="Topology")
    graph_uplink_overrides: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    map_default_filters: Mapped[dict | None] = mapped_column(JSONB)  # JSONB as of v0.2.0
    # The addresses agents are told to dial, declared by the operator. Distinct
    # from `api_base_url` above, which is the browser-facing URL: the address a
    # browser uses and the address an agent uses can legitimately differ, and
    # that difference is the whole LAN-versus-FQDN case this exists for.
    # Entries are {"id": str, "label": str, "url": str}. `id` is minted once and
    # never reused, because a label is mutable and cannot identify an endpoint
    # in an install command generated days earlier.
    # Empty means "not configured" — the install flow then falls back to
    # forwarded_base_url exactly as it does today.
    agent_endpoints: Mapped[list | None] = mapped_column(JSONB, nullable=False, default=list)
    # Font preferences
    ui_font: Mapped[str] = mapped_column(String, nullable=False, default="inter")
    ui_font_size: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    scan_progress_style: Mapped[str] = mapped_column(String, nullable=False, default="circuit")
    # CVE sync
    cve_sync_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cve_sync_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    cve_last_sync_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # Windscribe Integration
    windscribe_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    windscribe_feed_refresh_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Phase 3: Realtime / NATS settings
    realtime_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    realtime_transport: Mapped[str] = mapped_column(
        String, nullable=False, default="auto"
    )  # "auto" | "sse" | "websocket"
    # Phase 4: Discovery Engine 2.0 toggles
    listener_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    prober_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    deep_dive_max_parallel: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    scan_aggressiveness: Mapped[str] = mapped_column(String, nullable=False, default="normal")
    mdns_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ssdp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Feature 8: Federated Auth — JSONB as of v0.2.0
    oauth_providers: Mapped[dict | None] = mapped_column(
        JSONB
    )  # JSONB: {"github": {...}, "google": {...}}
    oidc_providers: Mapped[list | None] = mapped_column(JSONB)  # JSONB array of OIDC providers
    arp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tcp_probe_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Mobile / phone discovery
    mobile_discovery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mdns_multicast_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    mdns_listener_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    dhcp_lease_file_path: Mapped[str] = mapped_column(String, nullable=False, default="")
    # Router SSH for DHCP snooping (opt-in, vault-encrypted)
    dhcp_router_host: Mapped[str] = mapped_column(String, nullable=False, default="")
    dhcp_router_user_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    dhcp_router_pass_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    dhcp_router_command: Mapped[str] = mapped_column(
        String, nullable=False, default="cat /var/lib/misc/dnsmasq.leases"
    )
    # OPNsense integration
    opnsense_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opnsense_host: Mapped[str] = mapped_column(String, nullable=False, default="")
    opnsense_verify_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opnsense_api_key_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    opnsense_api_secret_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Fernet-encrypted
    # v0.2.0: Self-aware cluster
    self_cluster_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Phase 6.5: User management
    concurrent_sessions: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    login_lockout_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    login_lockout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    invite_expiry_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    masquerade_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_concurrent_scans: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # SMTP / Email delivery
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    smtp_host: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_username: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_password_enc: Mapped[str | None] = mapped_column(Text)  # Fernet-encrypted
    smtp_from_email: Mapped[str] = mapped_column(String, nullable=False, default="")
    smtp_from_name: Mapped[str] = mapped_column(String, nullable=False, default="Circuit Breaker")
    smtp_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    smtp_last_test_at: Mapped[str | None] = mapped_column(String)
    smtp_last_test_status: Mapped[str | None] = mapped_column(String)
    # ACME DNS-01 (INC-07). One provider per install: "cloudflare" or "rfc2136".
    # The config blob holds the provider's non-secret fields plus its credential as an
    # ``<key>_enc`` sibling — see services/acme_secrets.py. Nullable because DNS-01 is
    # opt-in; HTTP-01 needs nothing here.
    acme_dns_provider: Mapped[str | None] = mapped_column(String(32))
    acme_dns_config: Mapped[dict | None] = mapped_column(JSONB)
    # Phase 7: Vault encryption
    vault_key: Mapped[str | None] = mapped_column(
        Text
    )  # Plaintext key for DB fallback when env/file unwritable
    vault_key_hash: Mapped[str | None] = mapped_column(Text)  # SHA-256 of the vault key
    vault_key_rotation_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    vault_key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # cb-agent: server's static X25519 identity for the Noise IK agent link.
    # Hex-encoded private key, vault-encrypted at rest. Generated once on first
    # use by app.core.agent_crypto.
    agent_server_private_key: Mapped[str | None] = mapped_column(Text)
    # Task 28: server-key rotation with an overlap window. While a rotation is
    # in progress, `agent_server_key_pending_private_key` holds the
    # successor's vault-encrypted private key (same encoding as
    # agent_server_private_key above), and `agent_server_key_rotation_
    # overlap_expires_at` is the moment app.core.agent_crypto stops accepting
    # Noise handshakes against the *current* key and promotes the successor
    # into agent_server_private_key in its place (Global Constraints:
    # "Server-key overlap defaults to 7 days"). All three are set together by
    # start_server_key_rotation and cleared together by that same promotion —
    # never independently. `_started_at` is purely informational (surfaced on
    # the admin status endpoint); `_overlap_expires_at` is the actual gate.
    agent_server_key_pending_private_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_server_key_rotation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agent_server_key_rotation_overlap_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Slice 4.1: TLS trust rotation with an overlap window. The rotated unit
    # is a *policy*, not a digest: `agent_tls_pin_successor_mode` is
    # "self_signed" (with `agent_tls_pin_successor` holding the base64 SPKI
    # digest of the successor leaf) or "public" (with the successor column
    # empty, meaning agents should fall back to the system CA store). All
    # four are set together by agent_tls_pin.start_tls_pin_rotation and
    # cleared together by complete_tls_pin_rotation — never independently.
    #
    # Carrying the mode is what makes a self-signed <-> Let's Encrypt cutover
    # expressible at all. agent_install._tls_mode_and_pin returns an empty
    # pin for a letsencrypt certificate and a digest otherwise, and
    # tlsdial branches on which kind of verification applies, so a server
    # moving in either direction strands every agent that only learned a
    # digest.
    agent_tls_pin_successor_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_tls_pin_successor: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_tls_pin_rotation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    agent_tls_pin_rotation_overlap_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Phase 7.5: PostgreSQL backup retention
    db_backup_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # Security hardening
    scan_allowed_networks: Mapped[str] = mapped_column(
        Text, nullable=False, default='["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16"]'
    )  # JSON array of allowed CIDRs for scanning
    airgap_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ws_allowed_cidrs: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )  # JSON array of CIDRs allowed to connect via WebSocket; empty = allow all
    # Backup / DR settings (migration 0057)
    backup_s3_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_age_recipient: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_access_key_id: Mapped[str | None] = mapped_column(String, nullable=True)
    backup_s3_secret_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    backup_s3_region: Mapped[str] = mapped_column(String, nullable=False, default="us-east-1")
    backup_s3_prefix: Mapped[str] = mapped_column(
        String, nullable=False, default="circuitbreaker/backups/"
    )
    backup_s3_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    backup_local_retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Native monitor pipeline
    auto_monitor_on_discovery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    roles_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class DeviceRole(Base):
    """User-configurable device role catalog. Replaces hardcoded _VALID_ROLES / ROLE_RANK."""

    __tablename__ = "device_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    icon_slug: Mapped[str | None] = mapped_column(String, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_type_hints: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    hostname_patterns: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ── Onboarding (OOBE step state, Homarr-style) ─────────────────────────────────
# Single row (id=1). Only relevant when needs_bootstrap is True.


class Onboarding(Base):
    __tablename__ = "onboarding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    step: Mapped[str] = mapped_column(String, nullable=False, default="start")
    previous_step: Mapped[str] = mapped_column(String, nullable=False, default="start")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
