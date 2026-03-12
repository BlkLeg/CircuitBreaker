"""Async SQLAlchemy session factory for FastAPI-Users.

Uses the same database URL source as the sync engine so FastAPI-Users routes
like forgot-password and reset-password talk to the live PostgreSQL database.
PostgreSQL is required; SQLite is not supported for the async session.
"""

import os
from collections.abc import AsyncGenerator
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_sync_url: str = (
    os.environ.get("CB_DB_POOL_URL")
    or os.environ.get("CB_DB_URL")
    or settings.db_pool_url
    or settings.database_url
)

# PostgreSQL: replace sync driver with asyncpg
_pg_async = "postgresql+asyncpg://"
_async_url = (
    _sync_url.replace("postgresql://", _pg_async, 1)
    .replace("postgresql+psycopg2://", _pg_async, 1)
    .replace("postgres://", _pg_async, 1)
)

parsed = urlparse(_async_url)

# Disable SSL by default unless the URL explicitly requests it.
# asyncpg reads ~/.postgresql/postgresql.key even for Unix socket connections,
# which raises PermissionError in the container's read-only filesystem.
_connect_args: dict = {}
query = (parsed.query or "").lower()
ssl_explicitly_requested = any(
    kw in query
    for kw in ("sslmode=require", "sslmode=verify-full", "sslmode=verify-ca", "ssl=true")
)
if not ssl_explicitly_requested:
    _connect_args["ssl"] = False

async_engine = create_async_engine(
    _async_url,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
