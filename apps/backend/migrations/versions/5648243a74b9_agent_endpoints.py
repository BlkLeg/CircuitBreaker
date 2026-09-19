"""Add app_settings.agent_endpoints.

Revision ID: 5648243a74b9
Revises: 0108_agent_tls_pin_fp
Create Date: 2026-09-05

Lets an operator declare the address(es) agents should dial, instead of the
server guessing it from whatever hostname the admin's browser used. Distinct
from `api_base_url`, which is the browser-facing URL: the address a browser
uses and the address an agent uses can legitimately differ (LAN IP vs. public
FQDN), and that difference is the whole reason this column exists.

An empty list means "not configured" — the install flow falls back to
`forwarded_base_url` exactly as it does today, so this migration changes no
existing behaviour on its own.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5648243a74b9"
down_revision: str | None = "0108_agent_tls_pin_fp"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add app_settings.agent_endpoints, existence-guarded."""
    conn = op.get_bind()
    # Existence-guarded like every other migration here: 0001_init bootstraps
    # fresh databases from Base.metadata, which already carries this column.
    conn.execute(
        sa.text(
            "ALTER TABLE app_settings "
            "ADD COLUMN IF NOT EXISTS agent_endpoints JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )


def downgrade() -> None:
    """Drop app_settings.agent_endpoints."""
    op.get_bind().execute(sa.text("ALTER TABLE app_settings DROP COLUMN IF EXISTS agent_endpoints"))
