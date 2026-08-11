"""Require a one-time token for first-admin bootstrap.

Revision ID: 0102_bootstrap_setup_token
Revises: 0101_discovery_retention_and_global_pause
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0102_bootstrap_setup_token"
down_revision = "0101_discovery_retention_and_global_pause"
branch_labels = None
depends_on = None

_TABLE = "app_settings"
_COLUMNS = {
    "bootstrap_token_hash": sa.Column("bootstrap_token_hash", sa.Text(), nullable=True),
    "bootstrap_token_expires_at": sa.Column(
        "bootstrap_token_expires_at", sa.DateTime(timezone=True), nullable=True
    ),
    "bootstrap_token_used_at": sa.Column(
        "bootstrap_token_used_at", sa.DateTime(timezone=True), nullable=True
    ),
}


def _existing_columns() -> set[str]:
    inspector = sa_inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    existing = _existing_columns()
    for name, column in _COLUMNS.items():
        if name not in existing:
            op.add_column(_TABLE, column)


def downgrade() -> None:
    existing = _existing_columns()
    for name in reversed(tuple(_COLUMNS)):
        if name in existing:
            op.drop_column(_TABLE, name)
