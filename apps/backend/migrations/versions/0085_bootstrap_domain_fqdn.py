"""Add fqdn to app_settings

Revision ID: 0085_bootstrap_domain_fqdn
Revises: abec47e19d13
Create Date: 2026-07-22

"""

import sqlalchemy as sa
from alembic import op

revision = "0085_bootstrap_domain_fqdn"
down_revision = "abec47e19d13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0085")

    conn.execute(
        sa.text(
            f'ALTER TABLE "{current_schema}".app_settings '
            "ADD COLUMN IF NOT EXISTS fqdn VARCHAR NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    current_schema = conn.execute(sa.text("SELECT current_schema()")).scalar()
    if current_schema is None:
        raise RuntimeError("Unable to determine current schema for migration 0085")

    conn.execute(sa.text(f'ALTER TABLE "{current_schema}".app_settings DROP COLUMN IF EXISTS fqdn'))
