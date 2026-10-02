"""Runtime configuration, loaded from environment variables (and ``.env``).

Secrets never live in the source tree. ``SECRET_KEY`` has no default: the app
refuses to start without one, so a fresh clone can never run with a key that
is also sitting in a public repository.

Every field can be overridden with an environment variable of the same name
in upper case, e.g. ``DATABASE_URL`` or ``MAX_FAILED_LOGIN_ATTEMPTS``.
"""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing_extensions import Annotated


def _split_csv(value):
    """Allow list settings to be given as ``a,b,c`` in the environment."""
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- secrets and tokens -------------------------------------------------
    secret_key: str = Field(min_length=32)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # --- storage ------------------------------------------------------------
    # SQLite for now. For PostgreSQL use
    # postgresql+asyncpg://user:pass@host:5432/dbname (see docs/POSTGRES.md).
    database_url: str = "sqlite+aiosqlite:///./biometric_auth.db"

    # --- biometrics -----------------------------------------------------------
    match_threshold: float = 0.6
    face_confidence_threshold: float = 0.75
    # DeepFace's built-in anti-spoofing. Off by default: on a normal webcam in
    # room light it rejected genuine users too often. Re-test before enabling.
    deepface_anti_spoofing: bool = False

    # --- lockout and rate limits ---------------------------------------------
    max_failed_login_attempts: int = 3
    # Minutes an account stays locked after the 1st, 2nd, 3rd+ lock in a row.
    lockout_backoff_minutes: Annotated[List[int], NoDecode] = [1, 5, 15]
    login_rate_limit_per_minute: int = 10
    enroll_rate_limit_per_minute: int = 5
    refresh_rate_limit_per_minute: int = 30
    max_request_bytes: int = 4 * 1024 * 1024

    # --- network --------------------------------------------------------------
    # X-Forwarded-For is only trusted when the direct peer is one of these.
    trusted_proxies: Annotated[List[str], NoDecode] = []
    cors_origins: Annotated[List[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # --- risk engine ------------------------------------------------------------
    risk_score_stepup_threshold: float = 70
    risk_score_lockout_threshold: float = 90
    lm_studio_url: str = "http://localhost:1234/v1"
    gemma_temperature: float = 0.4

    # --- dev switches -----------------------------------------------------------
    # /demo/* endpoints inject fake risk signals. Never enable in a real deployment.
    demo_mode: bool = False
    # Create tables on startup with create_all() instead of Alembic. Only for
    # throwaway local databases; use `alembic upgrade head` otherwise.
    auto_create_tables: bool = False

    @field_validator("lockout_backoff_minutes", "trusted_proxies", "cors_origins", mode="before")
    @classmethod
    def _parse_csv(cls, value):
        # Pydantic then coerces each item to the field's type (int or str).
        return _split_csv(value)

    @field_validator("lockout_backoff_minutes")
    @classmethod
    def _backoff_not_empty(cls, value: List[int]) -> List[int]:
        if not value or any(v <= 0 for v in value):
            raise ValueError("lockout_backoff_minutes needs at least one positive value")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
