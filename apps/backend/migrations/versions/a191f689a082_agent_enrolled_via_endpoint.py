"""Add agents.enrolled_via_endpoint.

Revision ID: a191f689a082
Revises: 5648243a74b9
Create Date: 2026-09-05

Records the server_url an agent reported dialing at enrollment. The server has
no other way to know: it never connects to the agent, so an endpoint that
nothing can reach is otherwise invisible — the agent that would report the
failure is the one that cannot connect to report it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a191f689a082"
down_revision: str | None = "5648243a74b9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add agents.enrolled_via_endpoint, existence-guarded."""
    op.get_bind().execute(
        sa.text("ALTER TABLE agents ADD COLUMN IF NOT EXISTS enrolled_via_endpoint VARCHAR")
    )


def downgrade() -> None:
    """Drop agents.enrolled_via_endpoint."""
    op.get_bind().execute(
        sa.text("ALTER TABLE agents DROP COLUMN IF EXISTS enrolled_via_endpoint")
    )
