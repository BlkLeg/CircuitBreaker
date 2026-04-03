# apps/backend/migrations/versions/0077_add_opnsense_settings.py
"""add_opnsense_settings

Revision ID: 0077_add_opnsense_settings
Revises: 0076_mobile_discovery_settings
Create Date: 2026-04-02 00:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision: str = "0077_add_opnsense_settings"
down_revision: str | Sequence[str] | None = "0076_mobile_discovery_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = [
    ("opnsense_enabled", sa.Boolean(), False),
    ("opnsense_host", sa.String(), ""),
    ("opnsense_verify_ssl", sa.Boolean(), False),
    ("opnsense_api_key_enc", sa.Text(), None),
    ("opnsense_api_secret_enc", sa.Text(), None),
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
