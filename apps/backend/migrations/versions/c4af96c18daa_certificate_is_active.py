"""Record which certificate is actually served (INC-22).

Revision ID: c4af96c18daa
Revises: 0103_pending_audit_logs
Create Date: 2026-08-25

`nginx.mono.conf` serves $CB_DATA_DIR/tls/fullchain.pem, and nothing in
certificate_service.py ever wrote there. `is_active` is the row that says which
certificate belongs in that directory, and the partial unique index below is what
makes "at most one" a database rule rather than a convention application code can
forget. Two active certificates is a state where "what are we serving?" has no
answer, so Postgres refuses it outright.

This migration does not change what nginx serves. The entrypoint's self-signed pair
keeps being served until an operator activates a certificate through the API.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4af96c18daa"
down_revision: str | Sequence[str] | None = "0103_pending_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    # Existence-guarded like every other migration here: 0001_init bootstraps fresh
    # databases from the current Base.metadata, which already carries both the column
    # and the index.
    conn.execute(
        sa.text(
            "ALTER TABLE certificates "
            "ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE"
        )
    )
    conn.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_certificates_single_active "
            "ON certificates (is_active) WHERE is_active"
        )
    )

    # Adopt an existing certificate only when the answer is unambiguous. An install
    # with several certificates gets none marked and a page that says so, which is
    # honest — guessing here would change what the operator believes is being served.
    domain = os.environ.get("CB_DOMAIN", "").strip()
    if domain:
        conn.execute(
            sa.text("UPDATE certificates SET is_active = true WHERE domain = :d"),
            {"d": domain},
        )
    already_active = conn.execute(
        sa.text("SELECT count(*) FROM certificates WHERE is_active")
    ).scalar()
    if not already_active:
        conn.execute(
            sa.text(
                "UPDATE certificates SET is_active = true "
                "WHERE (SELECT count(*) FROM certificates) = 1"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_certificates_single_active"))
    conn.execute(sa.text("ALTER TABLE certificates DROP COLUMN IF EXISTS is_active"))
