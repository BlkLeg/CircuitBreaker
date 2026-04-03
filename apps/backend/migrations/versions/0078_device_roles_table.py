"""Add device_roles table; add roles_version to app_settings; add role_suggestion to scan_results.

Revision ID: 0078_device_roles_table
Revises: 0077_add_opnsense_settings
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0078_device_roles_table"
down_revision: str | Sequence[str] | None = "0077_add_opnsense_settings"
branch_labels = None
depends_on = None

_BUILTIN_ROLES = [
    # (slug, label, rank, device_type_hints, hostname_patterns)
    ("firewall", "Firewall", 1, [], []),
    ("router", "Router", 2, ["router"], []),
    ("switch", "Network Switch", 3, ["switch"], []),
    ("access_point", "WiFi AP", 4, ["access_point"], []),
    ("hypervisor", "Hypervisor", 5, [], []),
    ("server", "Server", 5, ["linux_server", "windows_pc"], []),
    ("nas", "NAS", 5, ["nas"], []),
    ("storage", "Storage", 5, [], []),
    ("compute", "Compute", 5, [], []),
    ("desktop", "Desktop", 5, ["desktop"], []),
    ("workstation", "Workstation", 5, [], []),
    ("mini_pc", "Mini PC", 5, [], []),
    ("raspberry_pi", "Raspberry Pi", 5, [], []),
    ("sbc", "Single Board Computer", 5, [], []),
    ("laptop", "Laptop", 5, ["laptop"], []),
    ("ups", "UPS", 5, [], []),
    ("pdu", "PDU", 5, [], []),
    ("ip_camera", "IP Camera", 5, ["ip_camera"], []),
    (
        "phone",
        "Smartphone",
        5,
        ["phone", "mobile_device", "ios_device"],
        [
            "iphone",
            "samsung",
            "galaxy",
            "pixel",
            "oneplus",
            "android",
            "motorola",
            "xiaomi",
            "huawei",
            "oppo",
            "vivo",
            "nokia",
        ],
    ),
    (
        "tablet",
        "Tablet",
        5,
        [],
        ["ipad", "kindle", "fire-hd", "galaxy-tab", "surface", "tab-"],
    ),
    ("smart_tv", "Smart TV", 5, ["smart_tv"], []),
    ("thermostat", "Thermostat", 5, [], []),
    ("printer", "Printer", 5, ["printer"], []),
    ("gaming_console", "Gaming Console", 5, [], []),
    ("voip_phone", "VoIP Phone", 5, ["voip_phone"], []),
    ("iot_device", "IoT Device", 5, ["iot_device"], []),
    ("vm", "VM", 5, [], []),
    ("lxc", "LXC", 5, [], []),
    ("misc", "Miscellaneous", 5, [], []),
]


def upgrade() -> None:
    op.create_table(
        "device_roles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("icon_slug", sa.String(), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "device_type_hints",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "hostname_patterns",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.add_column(
        "app_settings",
        sa.Column("roles_version", sa.Integer(), nullable=False, server_default="0"),
    )

    op.add_column(
        "scan_results",
        sa.Column("role_suggestion", sa.String(), nullable=True),
    )

    # Seed built-in roles
    now = datetime.now(UTC)
    device_roles_table = sa.table(
        "device_roles",
        sa.column("slug", sa.String),
        sa.column("label", sa.String),
        sa.column("rank", sa.Integer),
        sa.column("is_builtin", sa.Boolean),
        sa.column("device_type_hints", postgresql.JSONB),
        sa.column("hostname_patterns", postgresql.JSONB),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        device_roles_table,
        [
            {
                "slug": slug,
                "label": label,
                "rank": rank,
                "is_builtin": True,
                "device_type_hints": hints,
                "hostname_patterns": patterns,
                "created_at": now,
            }
            for slug, label, rank, hints, patterns in _BUILTIN_ROLES
        ],
    )


def downgrade() -> None:
    op.drop_column("scan_results", "role_suggestion")
    op.drop_column("app_settings", "roles_version")
    op.drop_table("device_roles")
