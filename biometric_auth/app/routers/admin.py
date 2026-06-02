"""Admin router: privileged account-recovery actions.

A single ``POST /admin/unblock/{user_id}`` endpoint, gated behind the ``admin``
role, reactivates a locked-out user and revokes their existing sessions so they
must authenticate fresh.

Unlike the auth routers, this write must land regardless of how the request
finishes, so it owns its own ``AsyncSessionLocal`` session and commits
explicitly — the request-scoped ``get_db`` rolls back on any ``HTTPException``,
which would silently discard the unblock.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import AuditLog, Session, User
from app.middleware.rbac import require_role

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.post(
    "/unblock/{user_id}",
    dependencies=[Depends(require_role("admin"))],
)
async def unblock_user(user_id: int):
    """Reactivate a locked user and revoke their sessions, persisting always.

    Uses ``AsyncSessionLocal`` directly (not ``get_db``) because the write must
    survive even when this handler later raises — ``get_db`` would roll it back.
    """
    try:
        async with AsyncSessionLocal() as db:
            # STEP 1 — resolve the target account.
            user = await db.get(User, user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            # STEP 2 — lift the lockout.
            user.is_active = True

            # STEP 3 — revoke every existing session so they log in fresh.
            await db.execute(
                update(Session)
                .where(Session.user_id == user_id)
                .values(is_revoked=True)
            )

            # STEP 4 — record who performed the unblock in the audit trail.
            log = AuditLog(
                user_id=user_id,
                action="admin_unblock",
                meta='{"unblocked_by": "admin"}',
            )
            db.add(log)

            # STEP 5 — commit the whole change set and confirm.
            await db.commit()
            return {
                "message": f"User {user_id} unblocked",
                "user_id": user_id,
            }
    except HTTPException:
        # A deliberate 404 passes through untouched — only genuinely unexpected
        # failures should be masked as the generic 500 below.
        raise
    except Exception as e:
        logger.exception("Unblock error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unblock user",
        )
