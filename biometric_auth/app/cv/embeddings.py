"""Face embedding extraction, serialization, and matching.

Wraps DeepFace's Facenet model: turn a pre-cropped face into a 1-D
embedding vector, persist it as JSON (for ``User.face_embedding``), and
compare two embeddings via cosine similarity. Locating the face is the
job of the upstream CV pipeline (``app.cv.detector`` / ``app.cv.stepup``);
by the time we get here a face is already confirmed.
"""

import json
import logging
from typing import Optional, Tuple

import numpy as np
from deepface import DeepFace

from app.cv.detector import FaceDetection  # noqa: F401 - part of the module's declared interface
from constants import MATCH_THRESHOLD

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "Facenet"


def extract_embedding(face_crop: np.ndarray) -> Optional[np.ndarray]:
    """Extract a Facenet embedding from an already-cropped face.

    ``enforce_detection=False`` is intentional: the CV pipeline already
    confirmed a face exists, so re-running detection here would be
    redundant. ``anti_spoofing=True`` means a presentation-attack crop
    raises inside DeepFace, which we catch and treat as a failure.

    Returns the embedding as a float32 array, or ``None`` if DeepFace
    raises for any reason (including spoof detection).
    """
    try:
        result = DeepFace.represent(
            img_path=face_crop,
            model_name=EMBEDDING_MODEL,
            enforce_detection=False,
            anti_spoofing=False,
        )
        embedding = result[0]["embedding"]
        return np.array(embedding, dtype=np.float32)
    except Exception as exc:
        logger.warning("Embedding extraction failed: %s", exc)
        return None


def embedding_to_json(embedding: np.ndarray) -> str:
    """Serialize an embedding to a JSON string for ``User.face_embedding``."""
    return json.dumps(embedding.tolist())


def json_to_embedding(json_str: str) -> Optional[np.ndarray]:
    """Deserialize a stored embedding back into a float32 array.

    Returns ``None`` if the stored value cannot be parsed.
    """
    try:
        parsed = json.loads(json_str)
        return np.array(parsed, dtype=np.float32)
    except Exception as exc:
        logger.warning("Embedding deserialization failed: %s", exc)
        return None


def compute_similarity(embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
    """Cosine similarity of two embeddings; 0.0 if either is a zero vector.

    Inputs are assumed to be valid arrays, so no error handling here.
    """
    dot = np.dot(embedding_a, embedding_b)
    norm_a = np.linalg.norm(embedding_a)
    norm_b = np.linalg.norm(embedding_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def is_match(embedding_a: np.ndarray, embedding_b: np.ndarray) -> Tuple[bool, float]:
    """Return ``(decision, raw_score)`` for two embeddings.

    Always returns both the boolean decision *and* the raw cosine score;
    the raw score is forwarded to Gemma as the ``face_similarity`` signal.
    """
    similarity = compute_similarity(embedding_a, embedding_b)
    return similarity >= MATCH_THRESHOLD, similarity
