"""remove_deprecated_features

Revision ID: f61dd2dc9ade
Revises: 0083_migrate_hardware_monitors
Create Date: 2026-07-14 13:56:20.772822

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f61dd2dc9ade"
down_revision: str | Sequence[str] | None = "0083_migrate_hardware_monitors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop foreign key and columns from hardware
    op.drop_constraint("fk_hardware_rack_id_racks", "hardware", type_="foreignkey")
    op.drop_column("hardware", "rack_id")
    op.drop_column("hardware", "u_height")
    op.drop_column("hardware", "rack_unit")
    op.drop_column("hardware", "mounting_orientation")
    op.drop_column("hardware", "side_rail")

    # Drop status tables
    op.drop_table("status_history")
    op.drop_table("status_groups")
    op.drop_table("status_pages")

    # Drop webhook tables
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_rules")

    # Drop racks
    op.drop_table("racks")


def downgrade() -> None:
    """Downgrade schema."""
    pass
