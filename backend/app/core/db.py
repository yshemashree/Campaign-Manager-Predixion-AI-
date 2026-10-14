"""PostgreSQL connection pool and sessions (SQLAlchemy 2.0, async, asyncpg driver)."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Checks a pooled connection is alive before handing it out, so a Postgres
        # restart doesn't surface as errors on the next few requests.
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit (we often return them).
    return async_sessionmaker(engine, expire_on_commit=False)


async def ping_database(engine: AsyncEngine) -> None:
    """Raises if Postgres can't run a trivial query."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
