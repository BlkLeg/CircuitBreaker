"""Retype certificates stored under a name their bytes do not match (INC-07).

Revision ID: 122698ed7f44
Revises: c4af96c18daa
Create Date: 2026-08-25

`create_certificate` branched on whether a PEM was pasted and never on the requested
type, so choosing "Let's Encrypt" without a PEM generated a self-signed certificate and
stored it with `type = 'letsencrypt'`. The Certificates page then reported a CA-issued
certificate where there was none.

Which rows are affected is determined by parsing the stored PEM — issuer == subject means
self-signed — rather than guessed. An unparseable PEM is left alone: relabelling a row we
cannot read would replace one wrong answer with another.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "122698ed7f44"
down_revision: str | Sequence[str] | None = "c4af96c18daa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from cryptography import x509

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, cert_pem FROM certificates WHERE type = 'letsencrypt'")
    ).fetchall()

    for row in rows:
        try:
            parsed = x509.load_pem_x509_certificate(row.cert_pem.encode())
        except Exception:  # noqa: BLE001 — an unparseable PEM is left alone, not guessed at
            continue
        if parsed.issuer == parsed.subject:
            conn.execute(
                sa.text("UPDATE certificates SET type = 'selfsigned' WHERE id = :i"),
                {"i": row.id},
            )


def downgrade() -> None:
    """Not reversible: the original mislabelling carried no record of which rows it applied to."""
