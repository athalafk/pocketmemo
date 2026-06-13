"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from pocketmemo.config import get_settings

_settings = get_settings()

_is_sqlite = _settings.database_url.startswith("sqlite")

if _is_sqlite:
    # SQLite is a single file: no connection-pool sizing, plus a busy timeout so
    # concurrent writes wait instead of erroring.
    engine: AsyncEngine = create_async_engine(
        _settings.database_url,
        echo=False,
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")  # FKs are off by default in SQLite
        cursor.execute("PRAGMA journal_mode=WAL")  # better read/write concurrency
        cursor.close()
else:
    engine = create_async_engine(
        _settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

# Active backend ("postgresql" or "sqlite"); selects the vector-search strategy.
DIALECT: str = engine.sync_engine.dialect.name

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a DB session that auto-closes."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
