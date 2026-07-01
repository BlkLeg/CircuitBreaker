from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context

from app.db.models import Base
from app.db.session import db_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def _widen_alembic_version_column(connection: sa.engine.Connection) -> None:
    """Widen version_num to VARCHAR(64) if it is still the SQLite-era VARCHAR(32).

    Alembic creates alembic_version before any migration runs.  Long revision
    IDs (e.g. '0016_webhook_deliveries_oauth_states', 36 chars) overflow the
    default column and cause a StringDataRightTruncation error at stamp time.
    """
    insp = sa.inspect(connection)
    if not insp.has_table("alembic_version"):
        return
    cols = {c["name"]: c for c in insp.get_columns("alembic_version")}
    col = cols.get("version_num")
    if col is None:
        return
    length = getattr(col.get("type"), "length", None)
    if length is not None and length < 64:
        connection.execute(
            sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        )


def run_migrations_online() -> None:
    """Run migrations using a direct DB connection (bypasses pgbouncer)."""
    from sqlalchemy import create_engine as _create_engine

    migration_engine = _create_engine(db_url)

    # Step 1: Widen alembic_version.version_num in its own committed transaction
    # BEFORE Alembic acquires the advisory lock and begins the migration transaction.
    # This is required because Alembic writes the revision ID (which can be >32 chars)
    # into alembic_version at the very start of the migration transaction — if the column
    # is still VARCHAR(32), that INSERT truncates and the entire migration run crashes.
    # Running the ALTER TABLE in a separate prior transaction ensures the schema change is
    # committed and visible before any migration logic executes. (#68)
    with migration_engine.connect() as pre_conn:
        _widen_alembic_version_column(pre_conn)
        pre_conn.commit()

    with migration_engine.begin() as connection:
        # Use pg_advisory_xact_lock (transaction-scoped) instead of pg_advisory_lock
        # (session-scoped). This is safe with pgbouncer transaction-pooling mode, which
        # returns the server connection to the pool at transaction commit — releasing a
        # session-level lock prematurely. Transaction-scoped locks are held until the
        # enclosing transaction commits or rolls back. (#66)
        connection.execute(sa.text("SELECT pg_advisory_xact_lock(872014001, 330619501)"))
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    migration_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
