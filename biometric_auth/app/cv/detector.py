import logging
from dataclasses import dataclass, field
from typing import List, Optional

import cv2
import numpy as np
from ultralytics import YOLO

from constants import FACE_CONFIDENCE_THRESHOLD


@dataclass
class FaceDetection:
    bbox: tuple  # (x1, y1, x2, y2) as ints
    confidence: float
    face_crop: any = field(default_factory=lambda: None)  # numpy array of the cropped face region

    def to_dict(self) -> dict:
        return {"bbox": self.bbox, "confidence": self.confidence}


class FaceDetector:
    def __init__(self, model_path: str = "weights/yolov8n-face.pt"):
        self.model_path = model_path
        self._model = None
        self.logger = logging.getLogger(__name__)

    def _get_model(self) -> YOLO:
        if self._model is None:
            self._model = YOLO(self.model_path)
            self.logger.info("Face detector model loaded")
        return self._model

    def detect(self, frame: np.ndarray) -> List[FaceDetection]:
        try:
            model = self._get_model()
            results = model(frame, verbose=False)

            detections: List[FaceDetection] = []
            frame_h, frame_w = frame.shape[:2]

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue
                for box in boxes:
                    confidence = float(box.conf[0])
                    if confidence < FACE_CONFIDENCE_THRESHOLD:
                        continue

                    x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])

                    # Crop with 10px padding, clamped to frame boundaries.
                    pad = 10
                    cx1 = max(0, x1 - pad)
                    cy1 = max(0, y1 - pad)
                    cx2 = min(frame_w, x2 + pad)
                    cy2 = min(frame_h, y2 + pad)
                    face_crop = frame[cy1:cy2, cx1:cx2]

                    detections.append(
                        FaceDetection(
                            bbox=(x1, y1, x2, y2),
                            confidence=confidence,
                            face_crop=face_crop,
                        )
                    )

            return detections
        except Exception as exc:
            self.logger.error("Face detection failed: %s", exc)
            return []

    def detect_best(self, frame: np.ndarray) -> Optional[FaceDetection]:
        detections = self.detect(frame)
        if not detections:
            return None
        return max(detections, key=lambda d: d.confidence)


face_detector = FaceDetector()
