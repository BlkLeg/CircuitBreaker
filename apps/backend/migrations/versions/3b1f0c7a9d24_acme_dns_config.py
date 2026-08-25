"""ACME DNS-01 provider, and the challenge each certificate was issued with (INC-07).

DNS-01 is what covers the installs with no public inbound, which for a homelab inventory
tool is most of them. The provider is one short string on app_settings; the credential
lives inside the JSONB blob as an ``<key>_enc`` sibling, encrypted with the vault key — see
``services/acme_secrets.py``.

``certificates.acme_challenge`` records the choice per row because renewal has to make it
again, unattended, months later — an install with no public inbound whose renewal silently
fell back to HTTP-01 would fail every night. It stays NULL for anything ACME did not issue
rather than defaulting to 'http-01', which would claim an issuance path those rows never
took. Nothing is backfilled for the same reason: existing letsencrypt rows predate any
working ACME path, and NULL is the honest record of that.

Revision ID: 3b1f0c7a9d24
Revises: 122698ed7f44
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b1f0c7a9d24"
down_revision: str | Sequence[str] | None = "122698ed7f44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existence-guarded like the rest of this tree: 0001_init bootstraps a fresh database
    # from the current Base.metadata, which already carries both columns.
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS acme_dns_provider VARCHAR(32)")
    )
    conn.execute(sa.text("ALTER TABLE app_settings ADD COLUMN IF NOT EXISTS acme_dns_config JSONB"))
    conn.execute(
        sa.text("ALTER TABLE certificates ADD COLUMN IF NOT EXISTS acme_challenge VARCHAR(16)")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE certificates ADD COLUMN IF NOT EXISTS acme_staging "
            "BOOLEAN NOT NULL DEFAULT false"
        )
    )


def downgrade() -> None:
    op.drop_column("certificates", "acme_staging")
    op.drop_column("certificates", "acme_challenge")
    op.drop_column("app_settings", "acme_dns_config")
    op.drop_column("app_settings", "acme_dns_provider")
