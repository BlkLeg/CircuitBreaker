"""Add body_template to webhook_rules.

Revision ID: 0056_webhook_body_template
Revises: 0055_webhook_dlq
Create Date: 2026-03-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056_webhook_body_template"
down_revision = "0055_webhook_dlq"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "webhook_rules",
        sa.Column("body_template", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("webhook_rules", "body_template")
