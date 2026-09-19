"""Record why a metric alert rule reached its assessment.

`metric_alert_states` stored the assessment and discarded the evaluator's reason
for it. Three distinct problems -- no samples, samples too stale, gaps too wide
to measure a breach across -- all surface as `unknown`, and they need three
different fixes, so the surface could report the state and never the cause.

Revision ID: 0116_metric_alert_reason_code
Revises: 0115_metric_alert_rules
Create Date: 2026-09-17
"""

from __future__ import annotations

from alembic import op

revision = "0116_metric_alert_reason_code"
down_revision = "0115_metric_alert_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like every additive column in this tree: a fresh install
    # gets its schema from 0001_init via create_all() over the live ORM
    # metadata, which already declares this column by the time this runs.
    #
    # Nullable with no backfill on purpose. NULL means "not evaluated since this
    # column existed", which is exactly true of every existing row -- inventing a
    # reason for a state decided before the column existed would be fabricating
    # evidence. The scheduled evaluator fills each row in on its next pass.
    op.execute("ALTER TABLE metric_alert_states ADD COLUMN IF NOT EXISTS reason_code VARCHAR(32)")


def downgrade() -> None:
    op.execute("ALTER TABLE metric_alert_states DROP COLUMN IF EXISTS reason_code")
