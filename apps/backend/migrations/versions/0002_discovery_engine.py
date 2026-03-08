"""Phase 4 Discovery Engine 2.0 — listener_events table + new scan columns + settings

Revision ID: c3f1a2b4d5e6
Revises: abd204157b2c
Create Date: 2026-03-06 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f1a2b4d5e6"
down_revision: str | Sequence[str] | None = "abd204157b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Phase 4: Discovery Engine 2.0 schema additions."""

    # ── listener_events (new table) ──────────────────────────────────────────
    op.create_table(
        "listener_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(), nullable=False),  # "mdns" | "ssdp"
        sa.Column("service_type", sa.String(), nullable=True),  # "_http._tcp.local."
        sa.Column("name", sa.String(), nullable=True),  # advertised service name
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("properties_json", sa.Text(), nullable=True),  # TXT records / SSDP headers
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_listener_events_seen_at"), "listener_events", ["seen_at"], unique=False
    )

    # ── scan_results — new Phase 4 columns ───────────────────────────────────
    op.add_column("scan_results", sa.Column("banner", sa.Text(), nullable=True))
    op.add_column("scan_results", sa.Column("os_accuracy", sa.Integer(), nullable=True))
    op.add_column(
        "scan_results",
        sa.Column("source_type", sa.String(), nullable=False, server_default="nmap"),
    )

    # ── scan_jobs — source_type ───────────────────────────────────────────────
    op.add_column(
        "scan_jobs",
        sa.Column("source_type", sa.String(), nullable=False, server_default="manual"),
    )

    # ── app_settings — Phase 4 discovery toggles ─────────────────────────────
    op.add_column(
        "app_settings",
        sa.Column("listener_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column(
        "app_settings",
        sa.Column("prober_interval_minutes", sa.Integer(), nullable=False, server_default="15"),
    )
    op.add_column(
        "app_settings",
        sa.Column("deep_dive_max_parallel", sa.Integer(), nullable=False, server_default="5"),
    )
    op.add_column(
        "app_settings",
        sa.Column("scan_aggressiveness", sa.String(), nullable=False, server_default="normal"),
    )
    op.add_column(
        "app_settings", sa.Column("mdns_enabled", sa.Boolean(), nullable=False, server_default="1")
    )
    op.add_column(
        "app_settings", sa.Column("ssdp_enabled", sa.Boolean(), nullable=False, server_default="1")
    )
    op.add_column(
        "app_settings", sa.Column("arp_enabled", sa.Boolean(), nullable=False, server_default="1")
    )
    op.add_column(
        "app_settings",
        sa.Column("tcp_probe_enabled", sa.Boolean(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    """Revert Phase 4 schema additions."""
    op.drop_column("app_settings", "tcp_probe_enabled")
    op.drop_column("app_settings", "arp_enabled")
    op.drop_column("app_settings", "ssdp_enabled")
    op.drop_column("app_settings", "mdns_enabled")
    op.drop_column("app_settings", "scan_aggressiveness")
    op.drop_column("app_settings", "deep_dive_max_parallel")
    op.drop_column("app_settings", "prober_interval_minutes")
    op.drop_column("app_settings", "listener_enabled")

    op.drop_column("scan_jobs", "source_type")

    op.drop_column("scan_results", "source_type")
    op.drop_column("scan_results", "os_accuracy")
    op.drop_column("scan_results", "banner")

    op.drop_index(op.f("ix_listener_events_seen_at"), table_name="listener_events")
    op.drop_table("listener_events")
