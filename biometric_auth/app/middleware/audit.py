"""Audit logging middleware.

Attaches the caller's identity (decoded from the JWT) to ``request.state`` so
downstream handlers and later middleware can read it without re-decoding, then
records one ``AuditLog`` row per request. Audit writes run on their own
session and are fully isolated from the request lifecycle — a logging failure
must never break a request that otherwise succeeded.
"""

import json
import logging
from typing import Callable, Optional

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.auth.jwt_service import decode_token
from app.database import AsyncSessionLocal
from app.models import AuditLog

logger = logging.getLogger(__name__)

# Routes that should NOT be logged (static files, health checks).
SKIP_LOGGING_PATHS = {"/docs", "/openapi.json", "/redoc", "/favicon.ico"}


class AuditMiddleware(BaseHTTPMiddleware):
    """Populate request.state with caller identity and persist an audit trail."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Optional[Response] = None
        try:
            # STEP 1 — attach the caller's identity to request.state.
            # Any non-Bearer header, missing token, or invalid token collapses
            # to the same "anonymous" state (all fields None).
            auth_header = request.headers.get("authorization", "")
            payload: Optional[dict] = None
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:]
                payload = decode_token(token)

            if payload is not None:
                request.state.user_id = int(payload.get("sub", 0))
                request.state.role = payload.get("role", "user")
                request.state.username = payload.get("username", "")
            else:
                request.state.user_id = None
                request.state.role = None
                request.state.username = None

            # STEP 2 — risk_score placeholder; RiskMiddleware (commit #11)
            # overwrites this once the risk engine has scored the request.
            request.state.risk_score = None

            # STEP 3 — process the request.
            response = await call_next(request)

            # STEP 4 — persist the audit entry (unless this path is skipped).
            if request.url.path not in SKIP_LOGGING_PATHS:
                await _write_audit_log(
                    user_id=request.state.user_id,
                    action=f"{request.method} {request.url.path}",
                    ip_address=_get_client_ip(request),
                    risk_score=request.state.risk_score,
                    meta=json.dumps({"status_code": response.status_code}),
                )

            # STEP 5 — return the response.
            return response
        except Exception:
            # Auditing must never take down a request. If we already produced a
            # response, return it. If not, the failure came from the downstream
            # app itself — re-raise so its error handling produces a proper
            # response instead of silently returning None.
            logger.exception("AuditMiddleware.dispatch failed")
            if response is not None:
                return response
            raise


async def _write_audit_log(
    user_id: Optional[int],
    action: str,
    ip_address: Optional[str],
    risk_score: Optional[float] = None,
    meta: Optional[str] = None,
) -> None:
    """Persist a single AuditLog row on a dedicated session.

    Middleware runs outside the request-scoped ``get_db`` lifecycle, so it
    cannot use FastAPI dependency injection and must manage its own session.
    """
    session: AsyncSession = AsyncSessionLocal()
    try:
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            risk_score=risk_score,
            ip_address=ip_address,
            meta=meta,
        )
        session.add(log_entry)
        await session.commit()
    except Exception:
        logger.warning("Failed to write audit log for %s", action, exc_info=True)
        await session.rollback()
    finally:
        await session.close()


def _get_client_ip(request: Request) -> str:
    """Best-effort client IP, honouring a proxy's X-Forwarded-For header."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
