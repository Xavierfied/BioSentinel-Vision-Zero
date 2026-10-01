"""Admin router: privileged account-recovery actions.

``POST /admin/unblock/{user_id}``, admin-only, lifts both kinds of lock (the
timed failed-login lock and a disable from the risk engine) and revokes the
user's sessions so they must authenticate fresh.

It owns its own ``AsyncSessionLocal`` session and commits explicitly, because
the request-scoped ``get_db`` rolls back on any ``HTTPException``.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.jwt_service import revoke_all_sessions
from app.auth.lockout import clear_lock
from app.database import AsyncSessionLocal
from app.middleware.rbac import require_role
from app.models import AuditLog, User
from app.security.net import get_client_ip

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


@router.post("/unblock/{user_id}")
async def unblock_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_role("admin")),
):
    """Reactivate a locked user and revoke their sessions."""
    try:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            clear_lock(user)
            await revoke_all_sessions(db, user_id, "admin_unblock")
            db.add(AuditLog(
                user_id=user_id,
                action="admin_unblock",
                ip_address=get_client_ip(request),
                meta=json.dumps({"unblocked_by": admin.id}),
            ))
            await db.commit()
            return {
                "message": f"User {user_id} unblocked",
                "user_id": user_id,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unblock error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to unblock user",
        )
