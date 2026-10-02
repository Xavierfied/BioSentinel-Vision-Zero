"""Timezone-aware UTC helpers.

SQLite stores datetimes without a timezone, PostgreSQL keeps it. Everything
in the app is UTC, so values read back without tzinfo are treated as UTC.
"""

from datetime import datetime, timezone
from typing import Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
