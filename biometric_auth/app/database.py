from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)

if engine.dialect.name == "sqlite":
    # The audit and risk middleware write on their own sessions alongside the
    # request's session. WAL plus a busy timeout lets those writers wait for
    # each other instead of failing with "database is locked".
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def create_tables() -> None:
    """Create every table directly. Only for throwaway databases and tests;
    real databases are managed with Alembic (`alembic upgrade head`)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    """Request-scoped session that commits on success, rolls back on error.

    Always declare it as ``Depends(get_db, scope="function")`` so the commit
    happens when the handler returns, before the response is sent. With the
    default scope the transaction stays open until after the response, and
    on SQLite the audit middleware's write then waits on the lock and fails.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
