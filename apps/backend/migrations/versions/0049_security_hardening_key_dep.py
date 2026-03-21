"""phase1_security_hardening

Revision ID: 715595fafdec
Revises: 0048_telemetry_timeseries_indexes
Create Date: 2026-03-20 17:24:24.601652

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "715595fafdec"
down_revision: str | Sequence[str] | None = "0048_telemetry_timeseries_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add client_hash_salt to app_settings, scopes to api_tokens."""
    # 1. Add client_hash_salt to app_settings
    op.add_column("app_settings", sa.Column("client_hash_salt", sa.Text(), nullable=True))

    # 2. Add scopes to api_tokens
    op.add_column(
        "api_tokens",
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("api_tokens", "scopes")
    op.drop_column("app_settings", "client_hash_salt")
