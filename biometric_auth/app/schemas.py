from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionOut(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    expires_at: datetime
    is_revoked: bool

    model_config = ConfigDict(from_attributes=True)


class AuditLogOut(BaseModel):
    id: int
    user_id: int | None
    action: str
    risk_score: float | None
    ip_address: str | None
    timestamp: datetime
    meta: str | None

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    username: str
    password: str


class EnrollRequest(BaseModel):
    username: str
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str
