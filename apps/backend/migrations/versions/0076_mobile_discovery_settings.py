"""mobile_discovery_settings

Revision ID: 0076_mobile_discovery_settings
Revises: 0075_add_kb_hostname_table
Create Date: 2026-04-01 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

# revision identifiers, used by Alembic.
revision: str = "0076_mobile_discovery_settings"
down_revision: str | Sequence[str] | None = "0075_add_kb_hostname_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = [
    ("mobile_discovery_enabled", sa.Boolean(), True),
    ("mdns_multicast_enabled", sa.Boolean(), True),
    ("mdns_listener_duration", sa.Integer(), 8),
    ("dhcp_lease_file_path", sa.String(), ""),
    ("dhcp_router_host", sa.String(), ""),
    ("dhcp_router_user_enc", sa.Text(), None),
    ("dhcp_router_pass_enc", sa.Text(), None),
    ("dhcp_router_command", sa.String(), "cat /var/lib/misc/dnsmasq.leases"),
]


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa_inspect(conn)
    existing = {c["name"] for c in insp.get_columns("app_settings")}

    for col_name, col_type, default in _NEW_COLUMNS:
        if col_name in existing:
            continue
        if default is None:
            op.add_column(
                "app_settings",
                sa.Column(col_name, col_type, nullable=True),
            )
        elif isinstance(default, bool):
            op.add_column(
                "app_settings",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=False,
                    server_default=sa.text("true" if default else "false"),
                ),
            )
        elif isinstance(default, int):
            op.add_column(
                "app_settings",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=False,
                    server_default=sa.text(str(default)),
                ),
            )
        else:
            op.add_column(
                "app_settings",
                sa.Column(
                    col_name,
                    col_type,
                    nullable=False,
                    server_default=sa.text(f"'{default}'"),
                ),
            )


def downgrade() -> None:
    for col_name, _, _ in _NEW_COLUMNS:
        op.drop_column("app_settings", col_name)
