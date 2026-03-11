"""Optimize schema with raw SQL optimizations from DB-Rewrite.md.

Revision ID: optimize_schema_0033
Revises: 0032_onboarding_step_state
Create Date: 2026-03-10 20:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "optimize_schema_0033"
down_revision = "0032_onboarding_step_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0015: CONCURRENTLY create GIN indexes
    # Note: CONCURRENTLY cannot run inside a transaction.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_users_name_trgm ON users USING GIN(display_name gin_trgm_ops)"
    )
    op.execute("BEGIN")

    # 0025 & 0045: Materialized Views with Refresh Rules
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS user_stats
        AS
        SELECT display_name AS name, COUNT(*) as total
        FROM users
        GROUP BY display_name
        WITH NO DATA;
    """)
    op.execute("""
        CREATE OR REPLACE RULE refresh_user_stats AS
        ON INSERT TO users
        WHERE (SELECT COUNT(*) FROM users) > 0 
        DO ALSO REFRESH MATERIALIZED VIEW user_stats;
    """)

    # 0030: Sequence optimization
    op.execute("""
        ALTER SEQUENCE IF EXISTS users_id_seq CACHE 1000;
    """)

    # 0035: Functions and Triggers
    op.execute("""
        CREATE OR REPLACE FUNCTION update_user_count()
        RETURNS TRIGGER AS $$
        BEGIN
            UPDATE user_stats
            SET total = (SELECT COUNT(*) FROM users)
            WHERE name = NEW.display_name;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 0040: Set Returning Functions
    op.execute("""
        CREATE OR REPLACE FUNCTION get_user_stats()
        RETURNS SETOF RECORD
        AS $$
        BEGIN
            RETURN QUERY SELECT name, COUNT(*) FROM users GROUP BY display_name;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 0055: Replication Configuration
    # Safe to ignore if replication is not natively enabled on the cluster, but conceptually included:
    op.execute("""
        SELECT pg_create_logical_replication_slot('repl_slot', 'pgoutput')
        WHERE NOT EXISTS (
            SELECT 1 FROM pg_replication_slots WHERE slot_name = 'repl_slot'
        );
    """)

    # 0060: Monitoring Tables
    op.create_table(
        "query_stats",
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("query"),
    )
    op.create_index("idx_query_stats_count", "query_stats", ["count"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_query_stats_count", table_name="query_stats")
    op.drop_table("query_stats")

    op.execute(
        "SELECT pg_drop_replication_slot('repl_slot') WHERE EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name = 'repl_slot');"
    )

    op.execute("DROP FUNCTION IF EXISTS get_user_stats();")
    op.execute("DROP FUNCTION IF EXISTS update_user_count() CASCADE;")

    op.execute("ALTER SEQUENCE IF EXISTS users_id_seq CACHE 1;")

    op.execute("DROP MATERIALIZED VIEW IF EXISTS user_stats CASCADE;")

    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_users_name_trgm;")
