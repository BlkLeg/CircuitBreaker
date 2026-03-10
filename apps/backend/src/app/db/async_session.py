"""Async SQLAlchemy session factory for FastAPI-Users.

Provides an AsyncEngine + async_sessionmaker that share the same SQLite file
as the sync engine in session.py.  WAL mode (set by the sync engine on first
connect) ensures concurrent sync/async access is safe.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_sync_url: str = settings.database_url

if _sync_url.startswith("sqlite"):
    _async_url = _sync_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    _connect_args: dict = {"check_same_thread": False}
else:
    # PostgreSQL: replace sync driver with asyncpg
    _pg_async = "postgresql+asyncpg://"
    _async_url = (
        _sync_url.replace("postgresql://", _pg_async, 1)
        .replace("postgresql+psycopg2://", _pg_async, 1)
        .replace("postgres://", _pg_async, 1)
    )
    _connect_args = {}

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
