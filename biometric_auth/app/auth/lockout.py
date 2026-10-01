"""Timed account lockout with backoff.

Replaces the old "three strikes and the account is disabled until an admin
steps in" rule, which let anyone who knew a username lock that person out.
Now a run of failures locks the account for a short, growing period
(``LOCKOUT_BACKOFF_MINUTES``, default 1, 5, then 15 minutes) and a successful
login clears the history.

Failures are written on their own database session because the request's
session is rolled back when the handler raises an HTTP error.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AuditLog, User
from app.timeutil import as_utc, utcnow

logger = logging.getLogger(__name__)


def locked_until(user: User) -> Optional[datetime]:
    """When the user's timed lock ends, or ``None`` if not locked now."""
    until = as_utc(user.locked_until)
    if until is not None and until > utcnow():
        return until
    return None


def _backoff_for(lock_count: int) -> timedelta:
    steps = settings.lockout_backoff_minutes
    return timedelta(minutes=steps[min(lock_count, len(steps)) - 1])


async def record_failure(
    user_id: int,
    reason_code: str,
    detail: str = "",
    ip: Optional[str] = None,
) -> Optional[datetime]:
    """Count one failed factor; returns the lock end time if this locked it."""
    async with AsyncSessionLocal() as session:
        try:
            user = await session.get(User, user_id)
            if user is None:
                return None

            session.add(AuditLog(
                user_id=user_id,
                action="login_failed",
                reason_code=reason_code,
                ip_address=ip,
                meta=json.dumps({"reason": detail or reason_code}),
            ))

            new_lock: Optional[datetime] = None
            user.failed_streak = (user.failed_streak or 0) + 1
            if user.failed_streak >= settings.max_failed_login_attempts:
                user.lock_count = (user.lock_count or 0) + 1
                new_lock = utcnow() + _backoff_for(user.lock_count)
                user.locked_until = new_lock
                user.failed_streak = 0
                session.add(AuditLog(
                    user_id=user_id,
                    action="account_locked",
                    reason_code="too_many_failures",
                    ip_address=ip,
                    meta=json.dumps({
                        "lock_count": user.lock_count,
                        "locked_until": new_lock.isoformat(),
                    }),
                ))
            await session.commit()
            return new_lock
        except Exception:
            logger.warning("Failed to record login failure for user %s", user_id, exc_info=True)
            await session.rollback()
            return None


def record_success(user: User) -> None:
    """Clear the failure history (caller's session commits it)."""
    user.failed_streak = 0
    user.lock_count = 0
    user.locked_until = None


def clear_lock(user: User) -> None:
    """Admin unlock: lift both the timed lock and an admin/risk disable."""
    record_success(user)
    user.is_active = True
