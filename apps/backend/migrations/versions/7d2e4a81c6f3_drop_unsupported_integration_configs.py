"""Remove integration configs for providers the product does not integrate with (INC-16).

``VALID_PROVIDERS`` accepted truenas and unifi with no sync implementation and no
``test_config`` branch, so a configuration for either was never usable for anything. Nothing
functional is lost by deleting them. What is gained is that the credentials stored alongside
them stop sitting in the database in a place the product can no longer reach to delete —
narrowing the accepted set without this migration would strand them there permanently.

Each removal is recorded in ``logs`` before it happens, because an operator who configured
one is entitled to find out where it went. It is written to ``logs`` and not ``audit_log``:
``db/models.py`` records that audit_log is trigger-populated and read-only from Python.

Revision ID: 7d2e4a81c6f3
Revises: 3b1f0c7a9d24
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d2e4a81c6f3"
down_revision: str | Sequence[str] | None = "3b1f0c7a9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROPPED = ("truenas", "unifi")


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, type, name, credential_id FROM integration_configs WHERE type = ANY(:types)"
        ),
        {"types": list(_DROPPED)},
    ).fetchall()

    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO logs (timestamp, level, category, action, entity_type, "
                "entity_id, details) VALUES (now(), 'warning', 'settings', "
                "'integration_config_removed', 'integration_config', :eid, :details)"
            ),
            {
                "eid": row.id,
                "details": (
                    f"Removed unsupported {row.type} integration '{row.name}' and its stored "
                    "credential (INC-16: no sync or test implementation ever existed)."
                ),
            },
        )

    # The config rows go first: credentials.id is a foreign key target here, so deleting a
    # credential while its config still points at it violates the constraint.
    conn.execute(
        sa.text("DELETE FROM integration_configs WHERE type = ANY(:types)"),
        {"types": list(_DROPPED)},
    )

    credential_ids = [row.credential_id for row in rows if row.credential_id is not None]
    if credential_ids:
        conn.execute(
            sa.text("DELETE FROM credentials WHERE id = ANY(:ids)"), {"ids": credential_ids}
        )


def downgrade() -> None:
    """Not reversible: the deleted credentials are ciphertext that was not kept."""
