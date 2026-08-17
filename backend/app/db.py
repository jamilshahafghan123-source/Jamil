"""Async SQLAlchemy engine, session factory, and schema bootstrap."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_models() -> None:
    """Create tables if they don't exist.

    Fine for a single-service deployment. If you later need versioned
    migrations, drop in Alembic and delete this call from startup.
    """
    from . import models  # noqa: F401  (registers mappers)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
