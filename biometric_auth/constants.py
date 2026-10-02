"""Backwards-compatible names for settings.

Values now come from environment variables via ``app.config``; nothing here is
hard-coded any more. New code should import ``settings`` from ``app.config``.
"""

from app.config import settings

MATCH_THRESHOLD = settings.match_threshold
RISK_SCORE_STEPUP_THRESHOLD = settings.risk_score_stepup_threshold
RISK_SCORE_LOCKOUT_THRESHOLD = settings.risk_score_lockout_threshold
FACE_CONFIDENCE_THRESHOLD = settings.face_confidence_threshold
LM_STUDIO_URL = settings.lm_studio_url
GEMMA_TEMPERATURE = settings.gemma_temperature
DATABASE_URL = settings.database_url
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes
REFRESH_TOKEN_EXPIRE_DAYS = settings.refresh_token_expire_days
MAX_FAILED_LOGIN_ATTEMPTS = settings.max_failed_login_attempts
ALGORITHM = settings.algorithm
