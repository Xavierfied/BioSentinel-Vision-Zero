import asyncio
from datetime import datetime

from app.database import AsyncSessionLocal
from app.models import AuditLog, User
from sqlalchemy import delete, select


async def reset_user() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == "testuser"))
        user = result.scalars().first()
        if user is None:
            raise SystemExit("testuser not found")
        user.is_active = True

        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        await db.execute(
            delete(AuditLog).where(
                AuditLog.user_id == user.id,
                AuditLog.action == "login_failed",
                AuditLog.timestamp >= today_start,
            )
        )
        await db.commit()
        print("testuser unlocked and failures cleared")


asyncio.run(reset_user())
