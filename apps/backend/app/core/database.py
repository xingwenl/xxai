from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_database(settings: Settings | None = None) -> AsyncEngine:
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    active_settings = settings or get_settings()
    _engine = create_async_engine(
        active_settings.database_url,
        echo=active_settings.database_echo,
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
    )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory

    if _session_factory is None:
        init_database()

    if _session_factory is None:
        raise RuntimeError("Database session factory is not initialized.")

    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


async def dispose_database() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _session_factory = None
