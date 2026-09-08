"""Add operator-corrected vulnerability assessment identities.

Revision ID: 0113_cve_assessment_identity
Revises: 0112_docker_sources
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0113_cve_assessment_identity"
down_revision = "0112_docker_sources"
branch_labels = None
depends_on = None

_TABLE = "entity_assessment_identities"


def upgrade() -> None:
    if _TABLE in set(sa_inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("vendor", sa.String(length=255), nullable=True),
        sa.Column("product", sa.String(length=255), nullable=True),
        sa.Column("version", sa.String(length=255), nullable=True),
        sa.Column("version_scheme", sa.String(length=32), nullable=True),
        sa.Column("provenance", sa.String(length=16), server_default="operator", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", name="uq_entity_assessment_identity_ref"),
    )
    op.create_index("ix_entity_assessment_identities_entity_type", _TABLE, ["entity_type"])
    op.create_index("ix_entity_assessment_identities_entity_id", _TABLE, ["entity_id"])


def downgrade() -> None:
    if _TABLE in set(sa_inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
