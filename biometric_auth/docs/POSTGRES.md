# Switching from SQLite to PostgreSQL

SQLite stays the default for now. Everything needed to switch is in place and
has been run end to end: Alembic migrations work on both databases, and
`scripts/sqlite_to_postgres.py` copies the data across.

## 1. Start PostgreSQL

```bash
docker compose -f docker-compose.postgres.yml up -d
pip install -r requirements-postgres.txt   # asyncpg driver
```

Or point at any PostgreSQL 14+ server you already run.

## 2. Create the schema

Run from `biometric_auth/`. Bring SQLite to the latest revision too, so both
match:

```bash
alembic upgrade head
alembic -x url=postgresql+asyncpg://biosentinel:biosentinel@localhost:5432/biosentinel upgrade head
```

## 3. Copy the data

```bash
python scripts/sqlite_to_postgres.py \
  --sqlite sqlite+aiosqlite:///./biometric_auth.db \
  --postgres postgresql+asyncpg://biosentinel:biosentinel@localhost:5432/biosentinel
```

The script refuses to run if the two databases are at different revisions or
the Postgres tables already have rows (add `--truncate` to clear them). It
copies parents before children and moves each id sequence past the copied
ids.

## 4. Switch the app

In `.env`:

```
DATABASE_URL=postgresql+asyncpg://biosentinel:biosentinel@localhost:5432/biosentinel
```

Restart the API. Keep `biometric_auth.db` until you have checked a login works.

## Notes

- New schema changes: edit `app/models.py`, then
  `alembic revision --autogenerate -m "what changed"`, review the file, and
  `alembic upgrade head`. Migrations use batch mode on SQLite automatically.
- Timestamps are `timestamptz` on PostgreSQL. SQLite stores them without a
  zone; the app treats every stored time as UTC.
