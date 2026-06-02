"""Heartbeat router: re-verify a live face for an already-authenticated session.

A single ``POST /heartbeat`` endpoint runs an uploaded frame through face
detection (``app.cv.stepup``) and a DeepFace embedding match
(``app.cv.embeddings``) against the caller's enrolled template, then stashes
the raw cosine similarity on ``request.state.face_similarity``. ``RiskMiddleware``
reads that value after the handler returns and feeds it to the Gemma risk
engine, so this path is where ongoing session risk is continuously re-scored.

Read-only with respect to the database, so the request-scoped ``get_db`` session
is sufficient — there is nothing here that must persist past an exception.
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.cv.embeddings import extract_embedding, is_match, json_to_embedding
from app.cv.stepup import step_up_detector
from app.database import get_db
from app.middleware.rbac import get_current_user
from app.models import User
from app.routers.enroll import _decode_image

router = APIRouter(tags=["monitoring"])
logger = logging.getLogger(__name__)


@router.post("/heartbeat")
async def heartbeat(
    request: Request,
    image: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-verify the caller's face mid-session and expose the similarity score.

    A missing face or unextractable embedding is reported as a soft outcome
    (``face_similarity`` of 0.0) rather than an error, so the risk engine still
    sees a conservative signal and can react. Only genuinely unexpected failures
    surface as a 500.
    """
    try:
        # STEP 1 — decode the uploaded frame into a BGR array (reuses enroll's).
        image_bytes = await image.read()
        frame = _decode_image(image_bytes)
        if frame is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not decode image",
            )

        # STEP 2 — locate the face; no face is a soft outcome that still feeds a
        # 0.0 similarity to RiskMiddleware rather than failing the request.
        detection = step_up_detector.detect(frame)
        if detection is None:
            request.state.face_similarity = 0.0
            return {
                "status": "no_face",
                "face_similarity": 0.0,
                "message": "No face detected in frame",
            }

        # STEP 3 — extract the live embedding; a spoof/low-quality crop comes
        # back as None and is likewise treated as a 0.0 similarity.
        live_embedding = extract_embedding(detection.face_crop)
        if live_embedding is None:
            request.state.face_similarity = 0.0
            return {
                "status": "no_embedding",
                "face_similarity": 0.0,
                "message": "Could not extract face embedding",
            }

        # STEP 4 — load the enrolled template; a corrupt one is a real 500.
        stored_embedding = json_to_embedding(current_user.face_embedding)
        if stored_embedding is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="User enrollment data corrupted",
            )

        # STEP 5 — compare and expose the raw score; RiskMiddleware reads
        # request.state.face_similarity before calling Gemma.
        matched, similarity = is_match(live_embedding, stored_embedding)
        request.state.face_similarity = similarity

        # STEP 6 — hand back the rounded score and match decision.
        return {
            "status": "ok",
            "face_similarity": round(similarity, 4),
            "matched": matched,
            "message": "Heartbeat received",
        }
    except HTTPException:
        # Deliberate 4xx/5xx outcomes pass through untouched — only genuinely
        # unexpected failures should be masked as the generic 500 below.
        raise
    except Exception as e:
        logger.exception("Heartbeat error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Heartbeat processing failed",
        )
