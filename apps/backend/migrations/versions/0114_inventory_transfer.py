"""Add durable portable inventory transfer previews and replay outcomes.

Revision ID: 0114_inventory_transfer
Revises: 0113_cve_assessment_identity
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql

revision = "0114_inventory_transfer"
down_revision = "0113_cve_assessment_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa_inspect(op.get_bind()).get_table_names())
    if "inventory_transfer_plans" not in tables:
        op.create_table(
            "inventory_transfer_plans",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), server_default="previewed", nullable=False),
            sa.Column("document_digest", sa.String(length=64), nullable=False),
            sa.Column("plan_digest", sa.String(length=64), nullable=False),
            sa.Column("inventory_digest", sa.String(length=64), nullable=False),
            sa.Column("document_json", postgresql.JSONB(), nullable=False),
            sa.Column("plan_json", postgresql.JSONB(), nullable=False),
            sa.Column("result_json", postgresql.JSONB(), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_inventory_transfer_plans_actor_id", "inventory_transfer_plans", ["actor_id"]
        )
        op.create_index(
            "ix_inventory_transfer_plans_status_expiry",
            "inventory_transfer_plans",
            ["status", "expires_at"],
        )
    if "inventory_transfer_operations" not in tables:
        op.create_table(
            "inventory_transfer_operations",
            sa.Column("id", sa.String(length=32), nullable=False),
            sa.Column("plan_id", sa.String(length=32), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("request_digest", sa.String(length=64), nullable=False),
            sa.Column("state", sa.String(length=16), server_default="applying", nullable=False),
            sa.Column("result_json", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["plan_id"], ["inventory_transfer_plans.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "actor_id", "idempotency_key", name="uq_inventory_transfer_operation_replay"
            ),
        )
        op.create_index(
            "ix_inventory_transfer_operations_actor_id",
            "inventory_transfer_operations",
            ["actor_id"],
        )


def downgrade() -> None:
    tables = set(sa_inspect(op.get_bind()).get_table_names())
    if "inventory_transfer_operations" in tables:
        op.drop_table("inventory_transfer_operations")
    if "inventory_transfer_plans" in tables:
        op.drop_table("inventory_transfer_plans")
