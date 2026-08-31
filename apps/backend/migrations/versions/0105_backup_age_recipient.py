"""Add the public age recipient used for encrypted off-host snapshots.

Revision ID: 0105_backup_age_recipient
Revises: 0104_bugbounty_20260826
Create Date: 2026-08-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0105_backup_age_recipient"
down_revision = "0104_bugbounty_20260826"
branch_labels = None
depends_on = None

_TABLE = "app_settings"
_COLUMN = "backup_age_recipient"


def _existing_columns() -> set[str]:
    inspector = sa_inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    # 0001_init bootstraps a fresh schema straight from app.db.models, so on a
    # fresh install app_settings already carries this column by the time we run.
    if _COLUMN not in _existing_columns():
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(), nullable=True))


def downgrade() -> None:
    if _COLUMN in _existing_columns():
        op.drop_column(_TABLE, _COLUMN)
