import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, User
from constants import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    REFRESH_TOKEN_EXPIRE_DAYS,
    SECRET_KEY,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload["type"] = "access"
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        days=REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload["type"] = "refresh"
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as exc:
        logger.warning("Token decode failed: %s", exc)
        return None


def create_token_pair(user_id: int, username: str, role: str) -> Tuple[str, str]:
    payload = {"sub": str(user_id), "username": username, "role": role}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    return access_token, refresh_token


async def save_session(
    db: AsyncSession,
    user_id: int,
    access_token: str,
    refresh_token: str,
) -> Session:
    payload = decode_token(access_token)
    exp = payload["exp"]
    expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)

    session = Session(
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )
    db.add(session)
    await db.flush()  # populate session.id without committing
    return session


async def revoke_session(db: AsyncSession, access_token: str) -> bool:
    result = await db.execute(
        select(Session).where(
            Session.access_token == access_token,
            Session.is_revoked == False,  # noqa: E712
        )
    )
    session = result.scalars().first()
    if session is None:
        return False

    session.is_revoked = True
    await db.flush()
    return True


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(
        select(User).where(
            User.username == username,
            User.is_active == True,  # noqa: E712
        )
    )
    return result.scalars().first()
