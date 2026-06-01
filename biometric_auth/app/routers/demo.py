"""Demo router: inject and clear synthetic risk signals for live walkthroughs.

Three admin-only endpoints write (or delete) ``AuditLog`` rows so a presenter
can drive the Gemma risk engine on demand: a sudden IP shift, a burst of rapid
actions, and a reset back to baseline. Every injected row uses a ``demo_``
action prefix so ``reset-signals`` can wipe them with a single ``LIKE`` match
without touching real audit history.

Each endpoint owns its own ``AsyncSessionLocal`` session and commits
explicitly, so the injected signals persist regardless of the request lifecycle.
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AuditLog
from app.middleware.rbac import require_role

router = APIRouter(prefix="/demo", tags=["demo"])
logger = logging.getLogger(__name__)


@router.post(
    "/trigger-ip-shift",
    dependencies=[Depends(require_role("admin"))],
)
async def trigger_ip_shift(user_id: int):
    """Inject two IP-bearing audit rows so the next heartbeat sees an IP shift.

    ``_assemble_signals`` compares the two most recent IP-bearing rows, so
    writing a local IP followed by a remote one makes ``ip_changed`` fire.
    """
    async with AsyncSessionLocal() as db:
        entries = [
            AuditLog(
                user_id=user_id,
                action="demo_signal",
                ip_address="192.168.1.100",
                meta='{"demo": "original_ip"}',
            ),
            AuditLog(
                user_id=user_id,
                action="demo_signal",
                ip_address="45.33.32.156",
                meta='{"demo": "shifted_ip"}',
            ),
        ]
        for e in entries:
            db.add(e)
        await db.commit()
    return {
        "message": "IP shift signal injected",
        "effect": "ip_changed=True on next heartbeat",
    }


@router.post(
    "/spam-requests",
    dependencies=[Depends(require_role("admin"))],
)
async def spam_requests(user_id: int):
    """Inject 20 rapid audit rows to spike the actions-per-minute signal."""
    async with AsyncSessionLocal() as db:
        now = datetime.utcnow()
        for i in range(20):
            db.add(
                AuditLog(
                    user_id=user_id,
                    action="demo_spam",
                    ip_address="127.0.0.1",
                    meta=f'{{"demo": "spam", "seq": {i}}}',
                )
            )
        await db.commit()
    return {
        "message": "20 rapid requests injected",
        "effect": "actions_per_minute spikes on next heartbeat",
    }


@router.post(
    "/reset-signals",
    dependencies=[Depends(require_role("admin"))],
)
async def reset_signals(user_id: int):
    """Delete all ``demo_``-prefixed audit rows for a user, restoring baseline."""
    async with AsyncSessionLocal() as db:
        from sqlalchemy import and_

        result = await db.execute(
            delete(AuditLog).where(
                and_(
                    AuditLog.user_id == user_id,
                    AuditLog.action.like("demo_%"),
                )
            )
        )
        await db.commit()
        deleted = result.rowcount
    return {
        "message": f"Cleared {deleted} demo signals",
        "effect": "Risk signals return to baseline",
    }
