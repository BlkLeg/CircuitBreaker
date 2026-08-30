"""Add the public age recipient used for encrypted off-host snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0105_backup_age_recipient"
down_revision = "0104_bugbounty_20260826"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("backup_age_recipient", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "backup_age_recipient")
