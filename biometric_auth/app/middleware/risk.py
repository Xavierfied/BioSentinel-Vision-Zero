"""Risk-scoring middleware.

Runs after the route handler on selected paths, gathers behavioural signals
from the audit trail, asks the local Gemma risk engine for a score, and acts
on it: a critical score locks the account, a high score forces step-up
authentication, anything lower passes through untouched.

Like ``AuditMiddleware``, this runs outside the request-scoped ``get_db``
lifecycle, so it manages its own ``AsyncSessionLocal`` sessions and cannot use
FastAPI dependency injection. Risk scoring is best-effort: any failure is
logged and the original response is returned — a scoring problem must never
take down a request that already succeeded.
"""

import logging
from datetime import datetime, timedelta
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.database import AsyncSessionLocal
from app.middleware.audit import _get_client_ip
from app.models import AuditLog, Session, User
from app.risk.engine import build_signal_dict, evaluate_risk
from constants import RISK_SCORE_LOCKOUT_THRESHOLD, RISK_SCORE_STEPUP_THRESHOLD

logger = logging.getLogger(__name__)

# Only these paths trigger full risk scoring. Scoring every request would
# hammer the Gemma engine; the heartbeat is where ongoing session risk is
# re-evaluated.
RISK_CHECK_PATHS = {"/heartbeat"}


class RiskMiddleware(BaseHTTPMiddleware):
    """Score risk on selected paths and enforce step-up / lockout thresholds."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Optional[Response] = None
        try:
            # STEP 1 — let the route run first; we score the request after the
            # handler has done its work.
            response = await call_next(request)

            # STEP 2 — only score the paths we care about.
            if request.url.path not in RISK_CHECK_PATHS:
                return response

            # STEP 3 — we can only score an authenticated caller. AuditMiddleware
            # populates request.state.user_id from the JWT (None if anonymous).
            user_id = getattr(request.state, "user_id", None)
            if user_id is None:
                return response

            # STEP 4 — assemble the behavioural signals from the audit trail.
            face_similarity = getattr(request.state, "face_similarity", 0.0)
            signals = await _assemble_signals(user_id, face_similarity, request)

            # STEP 5 — ask the local Gemma engine for a score + reason.
            score, reason = await evaluate_risk(signals)

            # STEP 6 — expose the score so AuditMiddleware records it on this
            # request's log row (it reads request.state.risk_score after us).
            request.state.risk_score = score

            # STEP 7 — act on the thresholds, most severe first.
            if score >= RISK_SCORE_LOCKOUT_THRESHOLD:
                await _handle_lockout(user_id)
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Account locked due to critical risk level",
                        "risk_score": score,
                        "reason": reason,
                    },
                )
            if score >= RISK_SCORE_STEPUP_THRESHOLD:
                await _handle_stepup(user_id)
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Step-up authentication required",
                        "risk_score": score,
                        "reason": reason,
                    },
                )

            # STEP 8 — score is within safe range; return the original response.
            return response
        except Exception:
            # Risk scoring must never crash the app. If the route already
            # produced a response, return it. If call_next itself failed, there
            # is no response to fall back on — re-raise so the app's own error
            # handling produces a proper response instead of returning None.
            logger.exception("RiskMiddleware.dispatch failed")
            if response is not None:
                return response
            raise


async def _assemble_signals(
    user_id: int,
    face_similarity: float,
    request: Request,
) -> dict:
    """Gather behavioural signals for ``user_id`` from the audit trail.

    Reads only behavioural metadata (IPs, counts, timestamps) — never images,
    embeddings, or tokens. On any failure, returns a safe-default signal dict
    (face_similarity passed through, everything else benign) so scoring can
    still proceed with a conservative picture.
    """
    session: AsyncSession = AsyncSessionLocal()
    try:
        # 1. Current client IP.
        ip = _get_client_ip(request)

        # 2. Did the IP change vs. the previous request? Look at the two most
        #    recent IP-bearing log rows: row[0] may be this very request, so we
        #    compare the prior one (row[1]) against the current IP.
        ip_result = await session.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_id, AuditLog.ip_address.is_not(None))
            .order_by(AuditLog.timestamp.desc())
            .limit(2)
        )
        recent_rows = ip_result.scalars().all()
        ip_changed = False
        if len(recent_rows) == 2 and recent_rows[1].ip_address != ip:
            ip_changed = True

        # 3. Failed login attempts since midnight (UTC).
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        failed_result = await session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.user_id == user_id,
                AuditLog.action.contains("failed"),
                AuditLog.timestamp >= today_start,
            )
        )
        failed_attempts_today = failed_result.scalar() or 0

        # 4. Request rate over the last 5 minutes, as actions per minute.
        five_min_ago = datetime.utcnow() - timedelta(minutes=5)
        actions_result = await session.execute(
            select(func.count(AuditLog.id)).where(
                AuditLog.user_id == user_id,
                AuditLog.timestamp >= five_min_ago,
            )
        )
        actions_count = actions_result.scalar() or 0
        actions_per_minute = float(actions_count) / 5.0

        # 5. Age of the caller's most recent active session, in minutes.
        session_result = await session.execute(
            select(Session)
            .where(Session.user_id == user_id, Session.is_revoked.is_(False))
            .order_by(Session.created_at.desc())
            .limit(1)
        )
        latest_session = session_result.scalar_one_or_none()
        session_age_minutes = 0
        if latest_session is not None:
            delta = datetime.utcnow() - latest_session.created_at.replace(tzinfo=None)
            session_age_minutes = int(delta.total_seconds() / 60)

        # 6. Hand the assembled signals to the engine's typed constructor.
        return build_signal_dict(
            face_similarity=face_similarity,
            ip_address=ip,
            ip_changed=ip_changed,
            hour_of_day=datetime.utcnow().hour,
            failed_attempts_today=failed_attempts_today,
            privilege_requested="/admin" in request.url.path,
            session_age_minutes=session_age_minutes,
            actions_per_minute=actions_per_minute,
        )
    except Exception:
        logger.warning("Failed to assemble risk signals for user %s", user_id, exc_info=True)
        return build_signal_dict(
            face_similarity=face_similarity,
            ip_address="",
            ip_changed=False,
            hour_of_day=0,
            failed_attempts_today=0,
            privilege_requested=False,
            session_age_minutes=0,
            actions_per_minute=0.0,
        )
    finally:
        await session.close()


async def _handle_lockout(user_id: int) -> None:
    """Deactivate the account and revoke all of its active sessions."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        user = await session.get(User, user_id)
        if user is not None:
            user.is_active = False
        await session.execute(
            update(Session)
            .where(Session.user_id == user_id)
            .where(Session.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        await session.commit()
        logger.warning("User %s locked out", user_id)
    except Exception:
        logger.warning("Failed to lock out user %s", user_id, exc_info=True)
        await session.rollback()
    finally:
        await session.close()


async def _handle_stepup(user_id: int) -> None:
    """Revoke all active sessions, forcing the caller to re-authenticate."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        await session.execute(
            update(Session)
            .where(Session.user_id == user_id)
            .where(Session.is_revoked.is_(False))
            .values(is_revoked=True)
        )
        await session.commit()
        logger.warning("Step-up triggered for user %s", user_id)
    except Exception:
        logger.warning("Failed to trigger step-up for user %s", user_id, exc_info=True)
        await session.rollback()
    finally:
        await session.close()
