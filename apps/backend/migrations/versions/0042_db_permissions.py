"""GRANT/REVOKE hardening — restrict public schema access.

Revision ID: 0042_db_permissions
Revises: 0041_telemetry_hypertable
Create Date: 2026-03-11

Removes implicit permissions from the ``public`` role and grants only the
necessary DML privileges to the ``breaker`` application role.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_db_permissions"
down_revision = "0041_telemetry_hypertable"
branch_labels = None
depends_on = None


def _role_exists(bind, role_name: str) -> bool:
    result = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role_name})
    return result.scalar() is not None


def upgrade() -> None:
    bind = op.get_bind()

    if not _role_exists(bind, "breaker"):
        return

    # Revoke blanket access from public
    op.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM public"))
    op.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM public"))

    # Grant only DML to breaker
    op.execute(
        sa.text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO breaker")
    )
    op.execute(sa.text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO breaker"))

    # Default privileges for future tables
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO breaker"
        )
    )
    op.execute(
        sa.text(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO breaker"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _role_exists(bind, "breaker"):
        return

    op.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO public"))
    op.execute(sa.text("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO public"))
