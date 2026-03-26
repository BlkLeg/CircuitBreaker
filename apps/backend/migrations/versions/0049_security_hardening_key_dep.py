"""phase1_security_hardening

Revision ID: 715595fafdec
Revises: 0048_telemetry_timeseries_indexes
Create Date: 2026-03-20 17:24:24.601652

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "715595fafdec"
down_revision: str | Sequence[str] | None = "0048_telemetry_timeseries_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema: add client_hash_salt to app_settings, scopes to api_tokens."""
    # Use IF NOT EXISTS to be idempotent — column may already exist if a prior
    # install partially applied this migration without updating the version table.
    op.execute("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS client_hash_salt TEXT")
    op.execute("ALTER TABLE api_tokens ADD COLUMN IF NOT EXISTS scopes JSONB")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("api_tokens", "scopes")
    op.drop_column("app_settings", "client_hash_salt")
