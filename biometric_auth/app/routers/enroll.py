"""Enrollment router: register a new user with a face-biometric template.

A single ``POST /enroll`` endpoint runs an uploaded frame through the full CV
cascade — liveness challenge, face detection (``app.cv.stepup``), then a
DeepFace embedding with anti-spoofing (``app.cv.embeddings``) — before
persisting the ``User`` and an ``enroll`` ``AuditLog`` row. The commit itself
is owned by ``get_db``; this module only ``flush``es to obtain the new id.
"""

import io
import logging
from typing import Optional

import cv2
import numpy as np
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt_service import get_user_by_username, hash_password
from app.cv.embeddings import embedding_to_json, extract_embedding
from app.cv.liveness import ChallengeType, LivenessChallenge, verify_challenge_frame
from app.cv.stepup import step_up_detector
from app.database import get_db
from app.models import AuditLog, User
from app.schemas import UserOut

router = APIRouter(prefix="/enroll", tags=["enrollment"])
logger = logging.getLogger(__name__)


def _decode_image(image_bytes: bytes) -> Optional[np.ndarray]:
    """Decode raw upload bytes into a BGR OpenCV frame.

    Goes bytes → PIL (forced to RGB so palette/grayscale/RGBA inputs
    normalise to three channels) → numpy → BGR, the channel order the rest
    of the CV pipeline expects. Returns ``None`` on any decode failure rather
    than raising, so the caller can map it to a clean 400.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("RGB")
        arr = np.array(image)
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    except Exception as exc:
        logger.warning("Image decode failed: %s", exc)
        return None


@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def enroll_user(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    image: UploadFile = File(...),
    challenge_type: str = Form(default="blink"),
    db: AsyncSession = Depends(get_db),
):
    """Enroll a new user from a username/password plus a single live face frame.

    Validates uniqueness, liveness, face presence and a non-spoofed embedding
    in turn — each failure surfaces as a specific 4xx — then writes the user
    and audit row. ``get_db`` commits on a clean return; any unexpected error
    rolls back via the same dependency and is reported as a generic 500.
    """
    try:
        # STEP 1 — reject duplicate usernames before doing any CV work.
        existing = await get_user_by_username(db, username)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already registered",
            )

        # STEP 2 — decode the uploaded frame into a BGR array.
        image_bytes = await image.read()
        frame = _decode_image(image_bytes)
        if frame is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not decode image",
            )

        # STEP 3 — confirm a live person via the requested challenge. An
        # unknown challenge_type falls back to BLINK rather than erroring.
        try:
            ct = ChallengeType(challenge_type)
        except ValueError:
            ct = ChallengeType.BLINK
        challenge = LivenessChallenge(challenge_type=ct, instruction="")
        passed, msg = verify_challenge_frame(frame, challenge)
        if not passed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Liveness check failed: {msg}",
            )

        # STEP 4 — locate the face (YOLO, escalating to RetinaFace).
        detection = step_up_detector.detect(frame)
        if detection is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No face detected in image",
            )

        # STEP 5 — extract the embedding; anti-spoofing lives inside DeepFace,
        # so a spoof/low-quality crop comes back as None.
        embedding = extract_embedding(detection.face_crop)
        if embedding is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Face verification failed. "
                    "Ensure good lighting and no obstructions."
                ),
            )

        # STEP 6 — persist the user; flush to get its id without committing.
        hashed_pw = hash_password(password)
        new_user = User(
            username=username,
            email=email,
            hashed_password=hashed_pw,
            face_embedding=embedding_to_json(embedding),
            role="user",
            is_active=True,
        )
        db.add(new_user)
        await db.flush()

        # STEP 7 — record the enrollment in the audit trail (same transaction).
        log = AuditLog(
            user_id=new_user.id,
            action="enroll",
            ip_address=None,
            risk_score=None,
            meta='{"status": "success"}',
        )
        db.add(log)

        # STEP 8 — get_db commits on return; UserOut serialises the ORM object.
        return new_user
    except HTTPException:
        # Deliberate 4xx outcomes pass through untouched — only genuinely
        # unexpected failures should be masked as a 500 below.
        raise
    except Exception as exc:
        logger.exception("Enrollment failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Enrollment failed",
        )
