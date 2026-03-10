"""Merge migration heads 0016 and 0019.

Revision ID: 0020_merge_heads
Revises: 0016_webhook_deliveries_oauth_states, b4a9c1d2e8f0
Create Date: 2026-03-08 00:00:00.000000

"""

from collections.abc import Sequence

revision: str = "0020_merge_heads"
down_revision: str | Sequence[str] | None = (
    "0016_webhook_deliveries_oauth_states",
    "b4a9c1d2e8f0",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
