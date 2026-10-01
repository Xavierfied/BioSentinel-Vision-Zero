"""Passwords, JWTs and server-side sessions.

Every token pair belongs to a row in ``sessions``. A token is only accepted
while that row is live, so revoking a session (logout, step-up, lockout)
ends it immediately instead of waiting for the token to expire.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Session, User
from app.timeutil import as_utc, utcnow

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)

ACCESS = "access"
REFRESH = "refresh"

# Verified against when the username does not exist, so a missing user costs
# the same bcrypt time as a wrong password and usernames cannot be probed.
_DUMMY_HASH = pwd_context.hash("not-a-real-password-" + secrets.token_hex(8))


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        return False


def burn_password_check(plain: str) -> None:
    """Spend one bcrypt verify on a dummy hash (timing equaliser)."""
    verify_password(plain, _DUMMY_HASH)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_jti() -> str:
    return secrets.token_urlsafe(24)


def _encode(claims: dict, token_type: str, expires_at: datetime) -> str:
    payload = dict(claims)
    payload.update({
        "type": token_type,
        "iat": int(utcnow().timestamp()),
        "exp": int(expires_at.timestamp()),
    })
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str, expected_type: Optional[str] = None) -> Optional[dict]:
    """Verify signature and expiry; optionally require a token type.

    Returns ``None`` on any failure, never raises.
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        logger.info("Token decode failed: %s", exc)
        return None
    if expected_type is not None and payload.get("type") != expected_type:
        return None
    for claim in ("sub", "sid", "jti"):
        if claim not in payload:
            return None
    return payload


def _token_pair(user: User, session_id: int, access_jti: str, refresh_jti: str) -> Tuple[str, str, datetime]:
    now = utcnow()
    base = {"sub": str(user.id), "username": user.username, "role": user.role, "sid": session_id}
    access = _encode({**base, "jti": access_jti}, ACCESS,
                     now + timedelta(minutes=settings.access_token_expire_minutes))
    refresh_expires = now + timedelta(days=settings.refresh_token_expire_days)
    refresh = _encode({**base, "jti": refresh_jti}, REFRESH, refresh_expires)
    return access, refresh, refresh_expires


async def create_session(db: AsyncSession, user: User) -> Tuple[str, str]:
    """Open a session row for ``user`` and return ``(access, refresh)``."""
    access_jti, refresh_jti = _new_jti(), _new_jti()
    session = Session(
        user_id=user.id,
        access_jti=access_jti,
        # Placeholders until the id exists; both are replaced below.
        refresh_token_hash=_new_jti(),
        expires_at=utcnow(),
    )
    db.add(session)
    await db.flush()  # populate session.id without committing

    access, refresh, refresh_expires = _token_pair(user, session.id, access_jti, refresh_jti)
    session.refresh_token_hash = hash_token(refresh)
    session.expires_at = refresh_expires
    await db.flush()
    return access, refresh


async def get_live_session(db: AsyncSession, payload: dict) -> Optional[Session]:
    """Return the session behind an *access* token payload, if still valid."""
    session = await db.get(Session, int(payload["sid"]))
    if session is None or session.is_revoked:
        return None
    if session.user_id != int(payload["sub"]):
        return None
    if session.access_jti != payload["jti"]:
        return None  # superseded by a refresh
    if as_utc(session.expires_at) <= utcnow():
        return None
    return session


async def rotate_session(db: AsyncSession, refresh_token: str) -> Optional[Tuple[str, str]]:
    """Exchange a refresh token for a new pair; the old pair stops working.

    Presenting a refresh token that was already rotated means it leaked (the
    real client already used it), so the whole session is revoked.
    """
    payload = decode_token(refresh_token, expected_type=REFRESH)
    if payload is None:
        return None

    session = await db.get(Session, int(payload["sid"]))
    if session is None or session.is_revoked or session.user_id != int(payload["sub"]):
        return None
    if as_utc(session.expires_at) <= utcnow():
        return None
    if session.refresh_token_hash != hash_token(refresh_token):
        logger.warning("Refresh token reuse on session %s; revoking", session.id)
        session.is_revoked = True
        session.revoked_reason = "refresh_reuse"
        await db.flush()
        return None

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None

    access_jti = _new_jti()
    access, refresh, _ = _token_pair(user, session.id, access_jti, _new_jti())
    session.access_jti = access_jti
    session.refresh_token_hash = hash_token(refresh)
    session.last_refreshed_at = utcnow()
    # The session keeps its original expiry: refreshing does not extend it.
    await db.flush()
    return access, refresh


async def revoke_session(db: AsyncSession, session_id: int, reason: str) -> bool:
    session = await db.get(Session, session_id)
    if session is None or session.is_revoked:
        return False
    session.is_revoked = True
    session.revoked_reason = reason
    await db.flush()
    return True


async def revoke_all_sessions(db: AsyncSession, user_id: int, reason: str) -> None:
    await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.is_revoked.is_(False))
        .values(is_revoked=True, revoked_reason=reason)
    )


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    """Look up a user by username, active or not (callers check status)."""
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()
