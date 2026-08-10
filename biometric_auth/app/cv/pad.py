"""Presentation Attack Detection (PAD) for webcam-captured face frames.

Runs three complementary texture/brightness signals on the face crop.
A quorum of 2/3 signals is required to flag an attack, so single-signal
failures from unusual (but legitimate) lighting conditions do not block
real users.

Signals
-------
1. Global Laplacian variance  — real skin has micro-texture; a photo
   displayed on a phone screen and re-captured by a webcam undergoes two
   rounds of JPEG compression that smooth this texture away.

2. Specular highlight ratio   — backlit phone screens produce large
   near-saturated bright regions across the face crop.  Natural skin
   specular highlights are small and localised (nose tip, forehead).

3. Block texture uniformity   — divide the crop into a 4×4 grid and
   measure how consistent the local Laplacian variance is across blocks.
   Real faces have wildly different texture zones (eyes vs cheeks vs
   forehead); screens render the same JPEG quality everywhere, so the
   block-level variances cluster tightly (low coefficient of variation).

Mode
----
PAD runs in ADVISORY mode by default (PAD_HARD_BLOCK = False).  In this
mode check_presentation_attack() always returns (False, reason) but logs
the raw signal values at WARNING level so the operator can observe real
thresholds before enabling hard blocking.

To enable hard blocking once thresholds are validated against your webcam:
  set PAD_HARD_BLOCK = True

Tuning (only matters when PAD_HARD_BLOCK = True)
---------
Lower TEXTURE_MIN_LAP_VAR  → catch more screens; risk more dim-room false positives.
Raise  SPECULAR_MAX_RATIO  → tolerate more glare; miss brighter screens.
Raise  BLOCK_CV_MIN        → catch more screens; risk false positives in even lighting.
"""

import logging
from typing import Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# --- thresholds ---------------------------------------------------------
TEXTURE_MIN_LAP_VAR    = 40.0   # global Laplacian variance; below = too smooth
SPECULAR_BRIGHT_THRESH = 228    # pixel value counted as near-saturated
SPECULAR_MAX_RATIO     = 0.18   # fraction of face region near-saturated → glow
BLOCK_CV_MIN           = 0.42   # CoV of 4×4 block variances; below = uniform (screen)
MIN_CROP_SIDE          = 48     # smaller crops are unreliable; skip PAD silently
QUORUM                 = 2      # signals that must agree to reject
PAD_HARD_BLOCK         = False  # True = reject frame; False = log only (advisory)
# ------------------------------------------------------------------------


def _texture_signal(gray: np.ndarray) -> Tuple[bool, float]:
    """Low global Laplacian variance → face is unusually smooth → screen."""
    var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return var < TEXTURE_MIN_LAP_VAR, var


def _specular_signal(gray: np.ndarray) -> Tuple[bool, float]:
    """Large fraction of near-saturated pixels → screen backlight glow."""
    ratio = float(np.sum(gray > SPECULAR_BRIGHT_THRESH)) / max(gray.size, 1)
    return ratio > SPECULAR_MAX_RATIO, ratio


def _uniformity_signal(gray: np.ndarray) -> Tuple[bool, float]:
    """Uniform block-level texture (low CoV) → screen rendering quality.

    Splits the crop into a 4×4 grid and computes Laplacian variance per
    block.  Real faces have very non-uniform local texture; phone-displayed
    faces have consistent JPEG quality across every region.
    """
    h, w = gray.shape
    bh, bw = max(1, h // 4), max(1, w // 4)
    variances = []
    for r in range(4):
        for c in range(4):
            block = gray[r * bh:(r + 1) * bh, c * bw:(c + 1) * bw]
            if block.size > 0:
                variances.append(float(cv2.Laplacian(block, cv2.CV_64F).var()))
    if len(variances) < 4:
        return False, 1.0
    arr = np.array(variances)
    mean = arr.mean()
    if mean < 1e-6:
        return True, 0.0
    cov = float(arr.std() / mean)
    return cov < BLOCK_CV_MIN, cov


def check_presentation_attack(face_crop: np.ndarray) -> Tuple[bool, str]:
    """Return ``(is_attack, reason)``.

    ``is_attack=True`` means the crop has presentation-attack signatures.
    Caller should surface this as a rejection *before* embedding extraction.
    Returns ``(False, "ok")`` on genuinely ambiguous crops so legitimate
    users are not blocked by lighting edge cases.
    """
    if face_crop is None or face_crop.size == 0:
        return False, "empty_crop"

    h = face_crop.shape[0]
    w = face_crop.shape[1]
    if h < MIN_CROP_SIDE or w < MIN_CROP_SIDE:
        logger.debug("PAD skipped — crop too small (%dx%d)", w, h)
        return False, "crop_too_small"

    gray = (
        cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        if face_crop.ndim == 3
        else face_crop.copy()
    )

    tex_flag,  tex_val  = _texture_signal(gray)
    spec_flag, spec_val = _specular_signal(gray)
    uni_flag,  uni_val  = _uniformity_signal(gray)

    flags = int(tex_flag) + int(spec_flag) + int(uni_flag)

    logger.debug(
        "PAD signals — laplacian_var=%.1f(%s) specular=%.3f(%s) "
        "block_cov=%.3f(%s) — quorum %d/%d",
        tex_val,  "FLAGGED" if tex_flag  else "ok",
        spec_val, "FLAGGED" if spec_flag else "ok",
        uni_val,  "FLAGGED" if uni_flag  else "ok",
        flags, QUORUM,
    )

    if flags >= QUORUM:
        parts = []
        if tex_flag:  parts.append(f"low_texture={tex_val:.1f}")
        if spec_flag: parts.append(f"screen_glow={spec_val:.1%}")
        if uni_flag:  parts.append(f"uniform_blocks={uni_val:.3f}")
        reason = "; ".join(parts)
        if PAD_HARD_BLOCK:
            logger.warning("PAD hard-blocked frame: %s", reason)
            return True, reason
        else:
            logger.warning(
                "PAD advisory (not blocking) — signals fired: %s "
                "| set PAD_HARD_BLOCK=True to enable rejection",
                reason,
            )

    return False, "ok"
