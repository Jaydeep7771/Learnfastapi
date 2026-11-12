"""Async engine + session factory (SQLAlchemy 2.0 style).

One engine per process owns the connection pool. Sessions are cheap, per-request,
and never shared across tasks (an AsyncSession is NOT concurrency-safe).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
)

SessionFactory = async_sessionmaker(
    engine,
    expire_on_commit=False,  # keep attributes readable after commit (no lazy IO in responses)
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency: yields a session, commits on success, rolls back on any exception.

    The code after `yield` is FastAPI's teardown phase - it runs even when the
    route raised, which is what makes this leak-free.
    """
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_models() -> None:
    """Dev-only schema creation. Use Alembic migrations in production."""
    from app import models  # noqa: F401  (import for side effect: register mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
