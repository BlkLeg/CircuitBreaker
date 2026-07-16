"""Add lan_discovery_desired toggle to app_settings

Revision ID: 0084_lan_discovery_desired_setting
Revises: ec2fa30c05d1
Create Date: 2026-07-15

"""

import sqlalchemy as sa
from alembic import op

revision = "0084_lan_discovery_desired_setting"
down_revision = "ec2fa30c05d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0084")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings '
            "ADD COLUMN IF NOT EXISTS lan_discovery_desired BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0084")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings '
            "DROP COLUMN IF EXISTS lan_discovery_desired"
        )
    )
