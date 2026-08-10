"""Liveness detection via active challenge-response.

Confirms a *live* person is in front of the camera — not a printed photo or
a replayed video — by issuing a random challenge (blink, or turn the head
left / right) and checking, frame by frame, whether the requested action
actually happens.

The geometry comes from MediaPipe's Face Mesh landmarks (468-point topology):
an eye-aspect-ratio for blinks, and the nose tip's horizontal offset between
the cheeks for head turns. Landmarks are produced by the MediaPipe Tasks
``FaceLandmarker`` (the current API; the legacy ``solutions.face_mesh`` was
removed upstream). MediaPipe is used for *landmarks only* — identity and
embeddings stay the job of ``app.cv.embeddings`` (DeepFace), and locating the
face for that pipeline is handled in ``app.cv.detector`` / ``app.cv.stepup``.
"""

import logging
import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple

import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    RunningMode,
)

logger = logging.getLogger(__name__)

# FaceLandmarker model asset, bundled alongside the YOLO weights. Emits the
# same 468-point Face Mesh topology the landmark indices below are defined on.
FACE_LANDMARKER_MODEL = "weights/face_landmarker.task"

# Landmark indices into the MediaPipe 468-point face mesh. Each eye set is
# ordered [outer, top-1, top-2, inner, bottom-2, bottom-1] so the eye-aspect-
# ratio can pair them as vertical (1,5) and (2,4) over horizontal (0,3).
LEFT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_LANDMARKS = [362, 385, 387, 263, 373, 380]
NOSE_TIP_INDEX = 1
LEFT_CHEEK_INDEX = 234
RIGHT_CHEEK_INDEX = 454

# Averaged eye-aspect-ratio below this means the eyes are closed (a blink).
EAR_BLINK_THRESHOLD = 0.20
# Nose offset across the face width; ~0.5 is centred. Turning the head moves
# the nose toward a cheek, past these bounds (mirror-view, as the user sees it).
HEAD_TURN_LEFT_OFFSET = 0.72
HEAD_TURN_RIGHT_OFFSET = 0.28


class ChallengeType(Enum):
    BLINK = "blink"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"


@dataclass
class LivenessChallenge:
    challenge_type: ChallengeType
    instruction: str  # human-readable, e.g. "Please blink both eyes"
    completed: bool = False
    frames_passed: int = 0


# Human-readable prompt shown to the user for each challenge type.
_CHALLENGE_INSTRUCTIONS = {
    ChallengeType.BLINK: "Please blink both eyes",
    ChallengeType.TURN_LEFT: "Please turn your head to the left",
    ChallengeType.TURN_RIGHT: "Please turn your head to the right",
}


def get_random_challenge() -> LivenessChallenge:
    """Pick a random challenge paired with its human-readable instruction."""
    challenge_type = random.choice(list(ChallengeType))
    return LivenessChallenge(
        challenge_type=challenge_type,
        instruction=_CHALLENGE_INSTRUCTIONS[challenge_type],
    )


def _euclidean(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two ``(x, y)`` points."""
    return float(np.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2))


def _eye_aspect_ratio(
    landmarks, eye_indices: List[int], img_w: int, img_h: int
) -> float:
    """Eye-aspect-ratio (EAR) for a single eye from its six mesh landmarks.

    Landmarks are read in the order given by ``eye_indices`` and converted from
    MediaPipe's normalised coordinates to pixels. EAR is the mean of the two
    vertical eyelid gaps over the horizontal eye width, so it trends toward 0
    as the eye closes. Returns ``0.0`` for a degenerate (zero-width) eye.
    """
    points = [
        (landmarks[idx].x * img_w, landmarks[idx].y * img_h)
        for idx in eye_indices
    ]

    v1 = _euclidean(points[1], points[5])
    v2 = _euclidean(points[2], points[4])
    h = _euclidean(points[0], points[3])

    if h == 0:
        return 0.0
    return (v1 + v2) / (2.0 * h)


def _detect_blink(landmarks, img_w: int, img_h: int) -> bool:
    """True when both eyes are closed (averaged EAR below the blink threshold)."""
    left_ear = _eye_aspect_ratio(landmarks, LEFT_EYE_LANDMARKS, img_w, img_h)
    right_ear = _eye_aspect_ratio(landmarks, RIGHT_EYE_LANDMARKS, img_w, img_h)
    avg_ear = (left_ear + right_ear) / 2
    return avg_ear < EAR_BLINK_THRESHOLD


def _detect_head_turn(landmarks, img_w: int, direction: str) -> bool:
    """True when the head is turned the requested way (``turn_left`` / ``turn_right``).

    Measures the nose tip's horizontal position relative to the two cheeks,
    normalised by face width so it is scale- and distance-invariant. The offset
    is ~0.5 facing forward, drops below 0.35 turning right, and rises above 0.65
    turning left (mirror-view). ``img_w`` is unused — coordinates are already
    normalised — but kept for signature symmetry with the other detectors.
    """
    nose_x = landmarks[NOSE_TIP_INDEX].x
    left_cheek_x = landmarks[LEFT_CHEEK_INDEX].x
    right_cheek_x = landmarks[RIGHT_CHEEK_INDEX].x

    face_width = abs(right_cheek_x - left_cheek_x)
    if face_width == 0:
        return False

    nose_offset = (nose_x - left_cheek_x) / face_width

    if direction == "turn_left":
        return nose_offset > HEAD_TURN_LEFT_OFFSET
    if direction == "turn_right":
        return nose_offset < HEAD_TURN_RIGHT_OFFSET
    return False


def verify_challenge_frame(
    frame: np.ndarray, challenge: LivenessChallenge
) -> Tuple[bool, str]:
    """Check whether ``challenge``'s requested action is present in ``frame``.

    Runs the MediaPipe Tasks ``FaceLandmarker`` on the single frame and
    dispatches to the matching detector. Returns ``(passed, message)``; a
    missing face or any internal error (including a missing model asset) yields
    ``(False, <reason>)`` rather than raising, so callers can drive a frame loop
    without guarding every call.

    cv2 is imported lazily so this module stays importable without OpenCV and
    the cost is only paid when a frame is actually verified. A fresh landmarker
    is built per call (``RunningMode.IMAGE`` — independent frames).
    """
    try:
        import cv2

        options = FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=FACE_LANDMARKER_MODEL),
            running_mode=RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
        )
        with FaceLandmarker.create_from_options(options) as landmarker:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = landmarker.detect(mp_image)

        if not result.face_landmarks:
            return (False, "No face detected in frame")

        landmarks = result.face_landmarks[0]
        img_h, img_w = frame.shape[:2]

        if challenge.challenge_type == ChallengeType.BLINK:
            detected = _detect_blink(landmarks, img_w, img_h)
        elif challenge.challenge_type == ChallengeType.TURN_LEFT:
            detected = _detect_head_turn(landmarks, img_w, "turn_left")
        elif challenge.challenge_type == ChallengeType.TURN_RIGHT:
            detected = _detect_head_turn(landmarks, img_w, "turn_right")
        else:
            detected = False

        if detected:
            return (True, "Challenge passed")
        return (False, f"Challenge not detected: {challenge.instruction}")
    except Exception as exc:
        logger.error("Liveness check error: %s", exc)
        return (False, "Liveness check error")
