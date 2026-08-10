"""Login router: authenticate an existing user with password + live face.

A single ``POST /auth/login`` endpoint runs the full step-up cascade —
password check, liveness challenge, face detection (``app.cv.stepup``), and a
DeepFace embedding match (``app.cv.embeddings``) against the enrolled template
— before issuing a JWT pair. Every failed factor is recorded as a
``login_failed`` ``AuditLog`` row, and repeated failures in a day deactivate
the account.

As in ``enroll``, the transaction itself is owned by ``get_db``; this module
only ``flush``es and never commits.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_service import (
    create_token_pair,
    get_user_by_username,
    save_session,
    verify_password,
)
from app.cv.embeddings import extract_embedding, is_match, json_to_embedding
from app.cv.liveness import ChallengeType, LivenessChallenge, verify_challenge_frame
from app.cv.pad import check_presentation_attack
from app.cv.stepup import step_up_detector
from app.database import AsyncSessionLocal, get_db
from app.models import AuditLog, User
from app.routers.enroll import _decode_image
from app.schemas import TokenResponse
from constants import ACCESS_TOKEN_EXPIRE_MINUTES, MAX_FAILED_LOGIN_ATTEMPTS

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)


async def _count_recent_failures(db: AsyncSession, user_id: int) -> int:
    """Count today's ``login_failed`` audit rows for a user.

    Failures are scoped to the current UTC day (from midnight) so the lockout
    counter resets daily rather than accumulating forever.
    """
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.user_id == user_id,
            AuditLog.action == "login_failed",
            AuditLog.timestamp >= today_start,
        )
    )
    return int(result.scalar_one())


async def _write_audit(
    db: AsyncSession,
    user_id: Optional[int],
    action: str,
    ip: Optional[str] = None,
    meta: Optional[str] = None,
) -> None:
    """Add an ``AuditLog`` row and flush it (no commit — ``get_db`` owns that)."""
    log = AuditLog(user_id=user_id, action=action, ip_address=ip, meta=meta)
    db.add(log)
    await db.flush()


async def _write_audit_persist(
    user_id: Optional[int],
    action: str,
    ip: Optional[str] = None,
    meta: Optional[str] = None,
) -> None:
    """Persist an audit row even when the request transaction rolls back."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        log = AuditLog(user_id=user_id, action=action, ip_address=ip, meta=meta)
        session.add(log)
        await session.commit()
    except Exception:
        logger.warning("Failed to persist audit log for %s", action, exc_info=True)
        await session.rollback()
    finally:
        await session.close()


async def _record_failed_attempt(user_id: int, reason: str) -> tuple[int, bool]:
    """Persist a login failure and return (failures_today, locked)."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        meta = json.dumps({"reason": reason})
        log = AuditLog(user_id=user_id, action="login_failed", meta=meta)
        session.add(log)
        await session.flush()

        failures = await _count_recent_failures(session, user_id)
        locked = False
        if failures >= MAX_FAILED_LOGIN_ATTEMPTS:
            user = await session.get(User, user_id)
            if user is not None and user.is_active:
                user.is_active = False
            locked = True

        await session.commit()
        return failures, locked
    except Exception:
        logger.warning("Failed to persist login failure", exc_info=True)
        await session.rollback()
        return MAX_FAILED_LOGIN_ATTEMPTS, False
    finally:
        await session.close()


async def _register_failed_attempt(
    db: AsyncSession, user: User, failures: int
) -> int:
    """Bump the in-request failure tally and lock the account at the threshold.

    Centralises the lockout decision shared by every failed factor (wrong
    password, liveness, embedding, face mismatch). Returns the updated tally so
    the caller can report the attempts remaining. When the threshold is reached
    it deactivates the user and raises HTTP 403, so the caller never falls
    through to its own (softer) error response.
    """
    failures += 1
    if failures >= MAX_FAILED_LOGIN_ATTEMPTS:
        user.is_active = False
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Too many failed attempts. Account locked.",
        )
    return failures


@router.post("/login", response_model=TokenResponse)
async def login(
    username: str = Form(...),
    password: str = Form(...),
    image: UploadFile = File(...),
    challenge_type: str = Form(default="blink"),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user via password, liveness, and face match; issue tokens.

    Factors are checked cheapest-first (existence → active → rate limit →
    password → liveness → detection → embedding match) so expensive CV work is
    only reached once the credentials clear. Each failed factor is audited and
    counts toward the daily lockout; only a clean pass mints a JWT pair.
    """
    try:
        # STEP 1 — resolve the account; an unknown user is a generic 401 so we
        # never reveal which half of the credentials was wrong.
        user = await get_user_by_username(db, username)
        if user is None:
            await _write_audit_persist(None, "login_failed", meta='{"reason": "user not found"}')
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        # STEP 2 — a deactivated account is locked out entirely.
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is locked. Contact administrator.",
            )

        # STEP 3 — enforce the daily failure cap before spending a password hash.
        failures = await _count_recent_failures(db, user.id)
        if failures >= MAX_FAILED_LOGIN_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account locked due to too many failed attempts.",
            )

        # STEP 4 — verify the password; a miss audits, counts, and may lock.
        if not verify_password(password, user.hashed_password):
            failures, locked = await _record_failed_attempt(user.id, "wrong password")
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Too many failed attempts. Account locked.",
                )
            remaining = MAX_FAILED_LOGIN_ATTEMPTS - failures
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid credentials. {remaining} attempt(s) remaining.",
            )

        # STEP 5 — decode the uploaded frame into a BGR array (reuses enroll's).
        image_bytes = await image.read()
        frame = _decode_image(image_bytes)
        if frame is None:
            await _write_audit_persist(
                user.id,
                "login_failed",
                meta='{"reason": "image decode failed"}',
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not decode image",
            )

        # STEP 6 — confirm a live person via the requested challenge; an unknown
        # challenge_type falls back to BLINK rather than erroring.
        try:
            ct = ChallengeType(challenge_type)
        except ValueError:
            ct = ChallengeType.BLINK
        challenge = LivenessChallenge(challenge_type=ct, instruction="")
        passed, msg = verify_challenge_frame(frame, challenge)
        if not passed:
            failures, locked = await _record_failed_attempt(
                user.id, f"liveness failed: {msg}"
            )
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Too many failed attempts. Account locked.",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Liveness check failed: {msg}",
            )

        # STEP 7 — locate the face (YOLO, escalating to RetinaFace).
        detection = step_up_detector.detect(frame)
        if detection is None:
            await _write_audit_persist(
                user.id,
                "login_failed",
                meta='{"reason": "no face detected"}',
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No face detected. Please retry.",
            )

        # STEP 7b — presentation attack detection: reject phone/print replays.
        # Counts as a failed login attempt to deter repeated spoofing.
        is_attack, pad_reason = check_presentation_attack(detection.face_crop)
        if is_attack:
            logger.warning("PAD rejected login frame for %s: %s", user.username, pad_reason)
            failures, locked = await _record_failed_attempt(
                user.id, f"presentation_attack: {pad_reason}"
            )
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Too many failed attempts. Account locked.",
                )
            remaining = MAX_FAILED_LOGIN_ATTEMPTS - failures
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Presentation attack detected — remove devices from frame "
                    f"and ensure only your face is visible. "
                    f"{remaining} attempt(s) remaining."
                ),
            )

        # STEP 8 — extract the embedding; anti-spoofing lives inside DeepFace, so
        # a spoof/low-quality crop comes back as None.
        live_embedding = extract_embedding(detection.face_crop)
        if live_embedding is None:
            failures, locked = await _record_failed_attempt(
                user.id, "spoof or embedding failed"
            )
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Too many failed attempts. Account locked.",
                )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Liveness check failed. Ensure good lighting.",
            )

        # STEP 9 — compare against the enrolled template.
        stored_embedding = json_to_embedding(user.face_embedding)
        if stored_embedding is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User enrollment data corrupted.",
            )
        matched, similarity = is_match(live_embedding, stored_embedding)
        if not matched:
            failures, locked = await _record_failed_attempt(
                user.id, f"face mismatch (similarity {similarity:.3f})"
            )
            if locked:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Too many failed attempts. Account locked.",
                )
            remaining = MAX_FAILED_LOGIN_ATTEMPTS - failures
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Face verification failed. {remaining} attempt(s) remaining.",
            )

        # STEP 10 — all factors cleared; mint the JWT pair and persist the session.
        access_token, refresh_token = create_token_pair(
            user.id, user.username, user.role
        )
        await save_session(db, user.id, access_token, refresh_token)

        # STEP 11 — record the successful login (committed by get_db on return).
        await _write_audit(
            db,
            user.id,
            "login_success",
            meta=f'{{"similarity": {similarity:.3f}}}',
        )

        # STEP 12 — hand back the tokens; expires_in is reported in seconds.
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
    except HTTPException:
        # Deliberate 4xx/5xx outcomes pass through untouched — only genuinely
        # unexpected failures should be masked as the generic 500 below.
        raise
    except Exception as e:
        logger.exception("Login error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )
