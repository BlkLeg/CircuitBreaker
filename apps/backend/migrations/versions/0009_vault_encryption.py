"""Vault encryption — add vault key fields to app_settings, add credentials table

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-03-07 16:00:00.000000

Adds:
  - app_settings: vault_key, vault_key_hash, vault_key_rotation_days, vault_key_rotated_at
  - credentials table (per-entity encrypted secret storage)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    # ── app_settings vault columns ─────────────────────────────────────────
    settings_cols = {c["name"] for c in inspector.get_columns("app_settings")}

    with op.batch_alter_table("app_settings") as batch_op:
        if "vault_key" not in settings_cols:
            batch_op.add_column(sa.Column("vault_key", sa.Text(), nullable=True))
        if "vault_key_hash" not in settings_cols:
            batch_op.add_column(sa.Column("vault_key_hash", sa.Text(), nullable=True))
        if "vault_key_rotation_days" not in settings_cols:
            batch_op.add_column(
                sa.Column(
                    "vault_key_rotation_days",
                    sa.Integer(),
                    nullable=False,
                    server_default="90",
                )
            )
        if "vault_key_rotated_at" not in settings_cols:
            batch_op.add_column(
                sa.Column("vault_key_rotated_at", sa.DateTime(timezone=True), nullable=True)
            )

    # ── credentials table ──────────────────────────────────────────────────
    existing_tables = inspector.get_table_names()
    if "credentials" not in existing_tables:
        op.create_table(
            "credentials",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "target_entity_id",
                sa.Integer(),
                nullable=True,
                comment="FK to the owning entity (hardware, discovery_profile, etc.)",
            ),
            sa.Column(
                "target_entity_type",
                sa.String(),
                nullable=True,
                comment="e.g. 'hardware', 'discovery_profile', 'app_settings'",
            ),
            sa.Column(
                "credential_type",
                sa.String(),
                nullable=False,
                comment="snmp | ssh | ipmi | smtp | api_key",
            ),
            sa.Column(
                "encrypted_value",
                sa.Text(),
                nullable=False,
                comment="Fernet-encrypted plaintext value",
            ),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "idx_credentials_entity",
            "credentials",
            ["target_entity_type", "target_entity_id"],
        )


def downgrade() -> None:
    op.drop_index("idx_credentials_entity", table_name="credentials")
    op.drop_table("credentials")

    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_column("vault_key_rotated_at")
        batch_op.drop_column("vault_key_rotation_days")
        batch_op.drop_column("vault_key_hash")
        batch_op.drop_column("vault_key")
