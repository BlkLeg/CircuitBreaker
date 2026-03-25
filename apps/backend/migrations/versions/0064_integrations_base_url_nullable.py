"""Allow integrations.base_url to be NULL (required for native/built-in monitor type)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064_integrations_base_url_nullable"
down_revision = "0063_proxmox_sync_health"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("integrations", "base_url", existing_type=sa.String(512), nullable=True)


def downgrade() -> None:
    op.alter_column("integrations", "base_url", existing_type=sa.String(512), nullable=False)
