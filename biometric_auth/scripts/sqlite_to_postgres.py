"""Copy every row from the SQLite database into PostgreSQL.

Run from biometric_auth/ after creating the Postgres schema:

    alembic -x url=postgresql+asyncpg://USER:PASS@HOST:5432/DB upgrade head
    python scripts/sqlite_to_postgres.py \
        --sqlite sqlite+aiosqlite:///./biometric_auth.db \
        --postgres postgresql+asyncpg://USER:PASS@HOST:5432/DB

Both databases must be at the same Alembic revision. The target tables must
be empty (use --truncate to clear them first). Tables are copied parent
first, and each table's id sequence is moved past the copied ids so new rows
do not collide.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import MetaData, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BATCH = 1000


async def _revision(engine) -> str:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        return result.scalar_one()


async def copy(sqlite_url: str, postgres_url: str, truncate: bool) -> None:
    source = create_async_engine(sqlite_url)
    target = create_async_engine(postgres_url)
    try:
        src_rev, dst_rev = await _revision(source), await _revision(target)
        if src_rev != dst_rev:
            raise SystemExit(
                f"Revision mismatch: SQLite is at {src_rev}, Postgres at {dst_rev}. "
                "Run `alembic upgrade head` on both first."
            )

        metadata = MetaData()
        async with source.connect() as conn:
            await conn.run_sync(metadata.reflect)
        tables = [t for t in metadata.sorted_tables if t.name != "alembic_version"]

        async with target.begin() as dst:
            if truncate:
                names = ", ".join(t.name for t in tables)
                await dst.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))

            for table in tables:
                count = (await dst.execute(select(func.count()).select_from(table))).scalar_one()
                if count:
                    raise SystemExit(f"Target table {table.name} is not empty; use --truncate.")

                copied = 0
                async with source.connect() as src:
                    result = await src.stream(select(table).order_by(*table.primary_key.columns))
                    async for chunk in result.mappings().partitions(BATCH):
                        await dst.execute(table.insert(), [dict(row) for row in chunk])
                        copied += len(chunk)

                if "id" in table.c:
                    await dst.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"
                    ))
                print(f"{table.name}: {copied} rows")
    finally:
        await source.dispose()
        await target.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", default="sqlite+aiosqlite:///./biometric_auth.db")
    parser.add_argument("--postgres", required=True)
    parser.add_argument("--truncate", action="store_true", help="empty the Postgres tables first")
    args = parser.parse_args()
    asyncio.run(copy(args.sqlite, args.postgres, args.truncate))


if __name__ == "__main__":
    main()
