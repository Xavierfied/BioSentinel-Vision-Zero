from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base
from app.timeutil import utcnow


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    face_embedding = Column(Text, nullable=True)
    role = Column(String(20), default="user")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    # False = disabled by an admin or by a critical risk score. Only an admin
    # can turn it back on. Failed logins use the timed lock below instead.
    is_active = Column(Boolean, default=True)

    # Timed lockout: failed_streak counts consecutive failures; hitting the
    # limit sets locked_until and bumps lock_count, which picks the next
    # (longer) backoff. A successful login resets both counters.
    failed_streak = Column(Integer, nullable=False, default=0, server_default="0")
    lock_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)

    sessions = relationship("Session", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")


class Session(Base):
    """One login. Tokens are never stored, only their identifiers and hashes.

    The access token carries ``sid`` (this row) and ``jti``; it is accepted
    only while the row is not revoked and ``access_jti`` still matches, so a
    refresh invalidates the previous access token. The refresh token is
    stored as a SHA-256 hash and rotated on every use.
    """

    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    access_jti = Column(String(64), nullable=False, unique=True, index=True)
    refresh_token_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    last_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    # When the refresh token (and so the whole session) expires.
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False)
    revoked_reason = Column(String(50), nullable=True)

    user = relationship("User", back_populates="sessions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(100), nullable=False)
    reason_code = Column(String(50), nullable=True)
    risk_score = Column(Float, nullable=True)
    ip_address = Column(String(45), nullable=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)
    meta = Column(Text, nullable=True)

    user = relationship("User", back_populates="audit_logs")
