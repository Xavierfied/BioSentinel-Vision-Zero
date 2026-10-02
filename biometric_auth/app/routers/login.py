"""Login router: password + live face, plus token refresh and logout.

``POST /auth/login`` runs password, liveness, face detection, PAD and a
DeepFace embedding match before opening a server-side session. Failed
factors count toward a timed lockout (``app.auth.lockout``).

``POST /auth/refresh`` rotates a refresh token, ``POST /auth/logout`` revokes
the caller's session, and ``GET /auth/me`` returns the caller's profile.

The request transaction is owned by ``get_db``; this module only flushes.
Failures are recorded on separate sessions so they survive the rollback.
"""

import json
import logging
import math
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import lockout
from app.auth.jwt_service import (
    burn_password_check,
    create_session,
    get_user_by_username,
    revoke_session,
    rotate_session,
    verify_password,
)
from app.config import settings
from app.cv.embeddings import extract_embedding, is_match, json_to_embedding
from app.cv.liveness import ChallengeType, LivenessChallenge, verify_challenge_frame
from app.cv.pad import check_presentation_attack
from app.cv.stepup import step_up_detector
from app.database import AsyncSessionLocal, get_db
from app.middleware.rbac import get_current_session, get_current_user
from app.models import AuditLog, Session, User
from app.routers.enroll import _decode_image
from app.schemas import RefreshRequest, TokenResponse, UserOut
from app.security.net import get_client_ip
from app.security.ratelimit import limit_per_ip
from app.security.uploads import read_jpeg_upload
from app.timeutil import utcnow

router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
)


async def _write_audit_persist(
    user_id: Optional[int],
    action: str,
    reason_code: Optional[str] = None,
    ip: Optional[str] = None,
    meta: Optional[str] = None,
) -> None:
    """Persist an audit row even when the request transaction rolls back."""
    async with AsyncSessionLocal() as session:
        try:
            session.add(AuditLog(
                user_id=user_id, action=action, reason_code=reason_code,
                ip_address=ip, meta=meta,
            ))
            await session.commit()
        except Exception:
            logger.warning("Failed to persist audit log for %s", action, exc_info=True)
            await session.rollback()


def _locked_response(until) -> HTTPException:
    minutes = max(1, math.ceil((until - utcnow()).total_seconds() / 60))
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Account temporarily locked. Try again in {minutes} minute(s).",
        headers={"Retry-After": str(minutes * 60)},
    )


async def _fail_factor(user: User, reason_code: str, detail: str, ip: str, message: str) -> None:
    """Record a failed factor (after the password passed) and raise."""
    new_lock = await lockout.record_failure(user.id, reason_code, detail, ip)
    if new_lock is not None:
        raise _locked_response(new_lock)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(limit_per_ip("login", lambda: settings.login_rate_limit_per_minute))],
)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    image: UploadFile = File(...),
    challenge_type: str = Form(default="blink"),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Authenticate with password, liveness and face match; open a session.

    The password is checked first and every wrong password gets the same
    generic 401, whether or not the username exists or is locked, so the
    endpoint cannot be used to discover accounts. Lock status is only
    revealed to a caller who already knows the password.
    """
    ip = get_client_ip(request)
    try:
        # STEP 1 — password. Unknown users burn the same bcrypt time.
        user = await get_user_by_username(db, username)
        if user is None:
            burn_password_check(password)
            await _write_audit_persist(None, "login_failed", "unknown_user", ip)
            raise _INVALID_CREDENTIALS

        current_lock = lockout.locked_until(user)
        if not verify_password(password, user.hashed_password):
            if current_lock is None and user.is_active:
                new_lock = await lockout.record_failure(user.id, "wrong_password", ip=ip)
                if new_lock is not None:
                    logger.info("User %s locked until %s", user.id, new_lock.isoformat())
            raise _INVALID_CREDENTIALS

        # STEP 2 — account state (only shown to someone with the password).
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled. Contact an administrator.",
            )
        if current_lock is not None:
            raise _locked_response(current_lock)

        # STEP 3 — decode the uploaded frame.
        image_bytes = await read_jpeg_upload(image)
        frame = _decode_image(image_bytes)
        if frame is None:
            await _write_audit_persist(user.id, "login_failed", "image_decode", ip)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not decode image",
            )

        # STEP 4 — liveness challenge on the frame. (Single-frame for now;
        # server-issued challenges over a clip replace this in the next phase.)
        try:
            ct = ChallengeType(challenge_type)
        except ValueError:
            ct = ChallengeType.BLINK
        challenge = LivenessChallenge(challenge_type=ct, instruction="")
        passed, msg = verify_challenge_frame(frame, challenge)
        if not passed:
            await _fail_factor(user, "liveness", msg, ip, f"Liveness check failed: {msg}")

        # STEP 5 — locate the face (YOLO, escalating to RetinaFace).
        detection = step_up_detector.detect(frame)
        if detection is None:
            await _write_audit_persist(user.id, "login_failed", "no_face", ip)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No face detected. Please retry.",
            )

        # STEP 6 — presentation attack detection (advisory unless
        # PAD_HARD_BLOCK is on in app.cv.pad).
        is_attack, pad_reason = check_presentation_attack(detection.face_crop)
        if is_attack:
            logger.warning("PAD rejected login frame for %s: %s", user.username, pad_reason)
            await _fail_factor(
                user, "presentation_attack", pad_reason, ip,
                "Presentation attack detected. Remove devices from the frame "
                "and make sure only your face is visible.",
            )

        # STEP 7 — embedding. Returns None if DeepFace fails on the crop (or
        # flags a spoof, when DEEPFACE_ANTI_SPOOFING is enabled).
        live_embedding = extract_embedding(detection.face_crop)
        if live_embedding is None:
            await _fail_factor(
                user, "embedding_failed", "", ip,
                "Face verification failed. Ensure good lighting.",
            )

        # STEP 8 — compare against the enrolled template.
        stored_embedding = json_to_embedding(user.face_embedding)
        if stored_embedding is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User enrollment data corrupted.",
            )
        matched, similarity = is_match(live_embedding, stored_embedding)
        if not matched:
            await _fail_factor(
                user, "face_mismatch", f"similarity {similarity:.3f}", ip,
                "Face verification failed.",
            )

        # STEP 9 — all factors passed: clear failures, open the session.
        lockout.record_success(user)
        access_token, refresh_token = await create_session(db, user)
        db.add(AuditLog(
            user_id=user.id,
            action="login_success",
            ip_address=ip,
            meta=json.dumps({"similarity": round(similarity, 3)}),
        ))
        await db.flush()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Login error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed",
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(limit_per_ip("refresh", lambda: settings.refresh_rate_limit_per_minute))],
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db, scope="function")):
    """Swap a refresh token for a new pair. Each refresh token works once."""
    pair = await rotate_session(db, body.refresh_token)
    if pair is None:
        # Commit a reuse-triggered revocation before reporting the failure.
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    access_token, refresh_token = pair
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: Session = Depends(get_current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """End the caller's session; its access and refresh tokens stop working."""
    await revoke_session(db, session.id, "logout")
    db.add(AuditLog(user_id=session.user_id, action="logout"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user
