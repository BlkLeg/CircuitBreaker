"""Apply public-schema GRANT hardening for the application DB user from the URL.

Revision ID: 0080_app_role_schema_grants
Revises: 0079_add_nmap_enabled_setting
Create Date: 2026-04-18

0042 granted only to the fixed role ``breaker``.  This migration repeats the same
REVOKE/GRANT and default-privilege pattern for whichever PostgreSQL role is used
in ``CB_DB_URL`` (so managed-Postgres users like ``cb_app`` receive the grants).
Idempotent: safe to re-run.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_app_role_schema_grants"
down_revision = "0079_add_nmap_enabled_setting"
branch_labels = None
depends_on = None


def _role_exists(bind: sa.engine.Connection, role_name: str) -> bool:
    result = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role_name})
    return result.scalar() is not None


def _quote_ident(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def upgrade() -> None:
    bind = op.get_bind()
    url = bind.engine.url
    role = (url.username or "breaker").strip() or "breaker"
    if not _role_exists(bind, role):
        return
    qi = _quote_ident(role)

    op.execute(sa.text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM public"))
    op.execute(sa.text("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM public"))

    op.execute(
        sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {qi}")
    )
    op.execute(sa.text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {qi}"))

    op.execute(
        sa.text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {qi}"
        )
    )
    op.execute(
        sa.text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {qi}"
        )
    )


def downgrade() -> None:
    pass
