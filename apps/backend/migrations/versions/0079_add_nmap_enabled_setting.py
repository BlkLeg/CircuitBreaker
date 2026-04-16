"""Add nmap_enabled toggle to app_settings

Revision ID: 0079_add_nmap_enabled_setting
Revises: 0078_device_roles_table
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0079_add_nmap_enabled_setting"
down_revision = "0078_device_roles_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0079")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings '
            "ADD COLUMN IF NOT EXISTS nmap_enabled BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0079")

    conn.execute(
        sa.text(f'ALTER TABLE "{current_schema}".app_settings DROP COLUMN IF EXISTS nmap_enabled')
    )
