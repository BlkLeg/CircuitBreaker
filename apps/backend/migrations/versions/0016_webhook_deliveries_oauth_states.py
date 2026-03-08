"""Add webhook_deliveries and oauth_states tables

Revision ID: 0016_webhook_deliveries_oauth_states
Revises: 567cc247f83c
Create Date: 2026-03-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016_webhook_deliveries_oauth_states"
down_revision: str | Sequence[str] | None = "567cc247f83c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create webhook_deliveries and oauth_states tables (idempotent)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    def _idxs(t):
        return {i["name"] for i in insp.get_indexes(t)} if t in tables else set()

    if "webhook_deliveries" not in tables:
        op.create_table(
            "webhook_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column(
                "rule_id",
                sa.Integer(),
                sa.ForeignKey("webhook_rules.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=False, default=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.String(), nullable=False),
        )

    if "ix_webhook_deliveries_rule_id" not in _idxs("webhook_deliveries"):
        op.create_index("ix_webhook_deliveries_rule_id", "webhook_deliveries", ["rule_id"])
    if "ix_webhook_deliveries_delivered_at" not in _idxs("webhook_deliveries"):
        op.create_index(
            "ix_webhook_deliveries_delivered_at", "webhook_deliveries", ["delivered_at"]
        )

    if "oauth_states" not in tables:
        op.create_table(
            "oauth_states",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("state", sa.String(), nullable=False, unique=True),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    if "ix_oauth_states_state" not in _idxs("oauth_states"):
        op.create_index("ix_oauth_states_state", "oauth_states", ["state"], unique=True)


def downgrade() -> None:
    """Drop webhook_deliveries and oauth_states tables."""
    op.drop_index("ix_oauth_states_state", table_name="oauth_states")
    op.drop_table("oauth_states")
    op.drop_index("ix_webhook_deliveries_delivered_at", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_rule_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
