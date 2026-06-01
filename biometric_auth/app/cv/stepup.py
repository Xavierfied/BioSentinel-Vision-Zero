import logging
import os
from typing import Optional

# Reduce TensorFlow/absl startup noise during RetinaFace imports.
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
logging.getLogger("tensorflow").setLevel(logging.ERROR)
logging.getLogger("absl").setLevel(logging.ERROR)

import numpy as np
from retinaface import RetinaFace

from app.cv.detector import FaceDetection, face_detector


class StepUpDetector:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # No model loading here — RetinaFace loads on first call (like YOLO).

    def detect(self, frame: np.ndarray) -> Optional[FaceDetection]:
        try:
            # Step 1: try the primary YOLO detector.
            detection = face_detector.detect_best(frame)
            if detection is not None:
                return detection

            # Step 2: YOLO found nothing — escalate to RetinaFace.
            return self._retinaface_detect(frame)
        except Exception as exc:
            self.logger.error("Step-up detection failed: %s", exc)
            return None

    def _retinaface_detect(self, frame: np.ndarray) -> Optional[FaceDetection]:
        try:
            results = RetinaFace.detect_faces(frame)

            # RetinaFace returns an int when no faces are found — guard against it.
            if not isinstance(results, dict) or not results:
                return None

            face = max(results.values(), key=lambda f: f["score"])

            x1, y1, x2, y2 = face["facial_area"]
            confidence = float(face["score"])

            # Crop with 10px padding, clamped to frame boundaries.
            frame_h, frame_w = frame.shape[:2]
            pad = 10
            cx1 = max(0, x1 - pad)
            cy1 = max(0, y1 - pad)
            cx2 = min(frame_w, x2 + pad)
            cy2 = min(frame_h, y2 + pad)
            face_crop = frame[cy1:cy2, cx1:cx2]

            return FaceDetection(
                bbox=(x1, y1, x2, y2),
                confidence=confidence,
                face_crop=face_crop,
            )
        except Exception as exc:
            self.logger.error("RetinaFace detection failed: %s", exc)
            return None


step_up_detector = StepUpDetector()
