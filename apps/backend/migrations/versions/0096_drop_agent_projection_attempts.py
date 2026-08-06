"""Drop the dead ``agent_host_samples.projection_attempts`` column and index.

Revision ID: 0096_drop_agent_projection_attempts
Revises: 0095_agent_host_telemetry

Projection into ``hardware_live_metrics`` happens in the *same* transaction as
the sample insert (``services/agent_telemetry.ingest_host_sample``), so a
persisted-but-unprojected row cannot exist and there is nothing to count.
``ix_agent_host_samples_projection`` supported a "find unprojected samples"
scan that no query performs — pure write amplification on a hypertable.
``projected_at`` stays; ``api/agents.py`` reports it.

0095 is unreleased and was corrected in place, so on a fresh install neither
object is ever created and this migration is a no-op. It exists for developers
who already applied the original 0095. Every step inspects first, so replaying
it is safe.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0096_drop_agent_projection_attempts"
down_revision = "0095_agent_host_telemetry"
branch_labels = None
depends_on = None

_TABLE = "agent_host_samples"
_INDEX = "ix_agent_host_samples_projection"
_COLUMN = "projection_attempts"


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa_inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _INDEX in {index["name"] for index in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {column["name"] for column in inspector.get_columns(_TABLE)}:
        # `agent_host_samples` may be a hypertable. 0095 sets no compression
        # policy on it, so a plain DROP COLUMN succeeds; if a future policy
        # ever makes Timescale reject it, surface that rather than silently
        # leaving a column the ORM no longer declares.
        op.drop_column(_TABLE, _COLUMN)


def downgrade() -> None:
    """Deliberately irreversible-by-omission.

    Recreating a column and an index nothing reads would only reintroduce the
    write amplification. The retry worker that would justify them belongs in
    the same migration as the code that reads them (D-3).
    """
    return
