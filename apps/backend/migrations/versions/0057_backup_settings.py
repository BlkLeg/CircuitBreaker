"""Add S3 backup settings columns to app_settings.

Revision ID: 0057_backup_settings
Revises: 0056_webhook_body_template
Create Date: 2026-03-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0057_backup_settings"
down_revision = "0056_webhook_body_template"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("backup_s3_bucket", sa.String(), nullable=True))
    op.add_column("app_settings", sa.Column("backup_s3_endpoint_url", sa.String(), nullable=True))
    op.add_column("app_settings", sa.Column("backup_s3_access_key_id", sa.String(), nullable=True))
    op.add_column("app_settings", sa.Column("backup_s3_secret_key_enc", sa.Text(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("backup_s3_region", sa.String(), nullable=False, server_default="us-east-1"),
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "backup_s3_prefix",
            sa.String(),
            nullable=False,
            server_default="circuitbreaker/backups/",
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("backup_s3_retention_count", sa.Integer(), nullable=False, server_default="30"),
    )
    op.add_column(
        "app_settings",
        sa.Column("backup_local_retention_count", sa.Integer(), nullable=False, server_default="7"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "backup_local_retention_count")
    op.drop_column("app_settings", "backup_s3_retention_count")
    op.drop_column("app_settings", "backup_s3_prefix")
    op.drop_column("app_settings", "backup_s3_region")
    op.drop_column("app_settings", "backup_s3_secret_key_enc")
    op.drop_column("app_settings", "backup_s3_access_key_id")
    op.drop_column("app_settings", "backup_s3_endpoint_url")
    op.drop_column("app_settings", "backup_s3_bucket")
