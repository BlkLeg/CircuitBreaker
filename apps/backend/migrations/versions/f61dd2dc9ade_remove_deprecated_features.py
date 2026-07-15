"""remove_deprecated_features

Revision ID: f61dd2dc9ade
Revises: 0083_migrate_hardware_monitors
Create Date: 2026-07-14 13:56:20.772822

Every drop is existence-guarded: 0001_init bootstraps fresh databases from
the *current* Base.metadata, which no longer contains the racks table or the
hardware rack columns, so on fresh installs there is nothing to drop here.
Only databases that predate the removal still carry these objects.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f61dd2dc9ade"
down_revision: str | Sequence[str] | None = "0083_migrate_hardware_monitors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Drop foreign key and columns from hardware. The FK name differs between
    # metadata-created and historical databases — look it up dynamically.
    hw_cols = {c["name"] for c in insp.get_columns("hardware")}
    if "rack_id" in hw_cols:
        for fk in insp.get_foreign_keys("hardware"):
            if fk.get("constrained_columns") == ["rack_id"]:
                op.drop_constraint(fk["name"], "hardware", type_="foreignkey")
    for col in ("rack_id", "u_height", "rack_unit", "mounting_orientation", "side_rail"):
        if col in hw_cols:
            op.drop_column("hardware", col)

    # Drop status, webhook, and racks tables (order respects FK dependencies).
    for table in (
        "status_history",
        "status_groups",
        "status_pages",
        "webhook_deliveries",
        "webhook_rules",
        "racks",
    ):
        if insp.has_table(table):
            op.drop_table(table)


def downgrade() -> None:
    """Downgrade schema."""
    pass
