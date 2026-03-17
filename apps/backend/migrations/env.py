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
    with migration_engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            _widen_alembic_version_column(connection)
            context.run_migrations()
    migration_engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
