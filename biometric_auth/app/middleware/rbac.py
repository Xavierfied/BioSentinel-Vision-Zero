import logging

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_service import ACCESS, decode_token, get_live_session
from app.database import get_db
from app.models import Session, User

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_session(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Session:
    """Resolve the caller's live session from a Bearer access token.

    Rejects tokens that are badly signed, expired, not access tokens, from a
    revoked session, or superseded by a refresh.
    """
    if credentials is None:
        raise _UNAUTHORIZED
    payload = decode_token(credentials.credentials, expected_type=ACCESS)
    if payload is None:
        raise _UNAUTHORIZED
    session = await get_live_session(db, payload)
    if session is None:
        raise _UNAUTHORIZED
    request.state.session_id = session.id
    return session


async def get_current_user(
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> User:
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is inactive",
        )
    return user


def require_role(*roles: str):
    async def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorised for this endpoint",
            )
        return current_user

    return role_checker
