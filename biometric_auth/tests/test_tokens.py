"""Sessions, revocation, refresh rotation and forged tokens."""

from datetime import timedelta

from jose import jwt
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Session
from app.timeutil import utcnow
from tests.conftest import bearer

OLD_PUBLIC_KEY = "this-is-the-ultra-secret-code-idk-why-am-i-typing-this"


async def _tokens(login, make_user, cv):
    await make_user()
    resp = await login()
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_login_returns_working_tokens(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    me = await client.get("/auth/me", headers=bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


async def test_sessions_store_no_raw_tokens(login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(Session))).scalars().one()
    stored = " ".join(str(getattr(row, c.name)) for c in Session.__table__.columns)
    assert tokens["access_token"] not in stored
    assert tokens["refresh_token"] not in stored


async def test_logout_kills_access_and_refresh(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    out = await client.post("/auth/logout", headers=bearer(tokens["access_token"]))
    assert out.status_code == 204
    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 401
    again = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert again.status_code == 401


async def test_refresh_rotates_and_old_access_dies(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    resp = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    new = resp.json()
    assert new["refresh_token"] != tokens["refresh_token"]
    assert (await client.get("/auth/me", headers=bearer(new["access_token"]))).status_code == 200
    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 401


async def test_refresh_reuse_revokes_whole_session(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    first = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    new = first.json()
    replay = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    # The legitimate holder's fresh tokens die too: the token leaked.
    assert (await client.get("/auth/me", headers=bearer(new["access_token"]))).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": new["refresh_token"]})).status_code == 401


async def test_token_types_are_not_interchangeable(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    assert (await client.get("/auth/me", headers=bearer(tokens["refresh_token"]))).status_code == 401
    swapped = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert swapped.status_code == 401


async def test_token_signed_with_old_public_key_is_rejected(client, make_user):
    user = await make_user(role="admin")
    forged = jwt.encode(
        {"sub": str(user.id), "username": "alice", "role": "admin", "sid": 1, "jti": "x",
         "type": "access", "exp": int((utcnow() + timedelta(hours=1)).timestamp())},
        OLD_PUBLIC_KEY, algorithm="HS256",
    )
    assert (await client.get("/auth/me", headers=bearer(forged))).status_code == 401
    assert (await client.post(f"/admin/unblock/{user.id}", headers=bearer(forged))).status_code == 401


async def test_validly_signed_token_without_session_is_rejected(client, make_user):
    user = await make_user()
    token = jwt.encode(
        {"sub": str(user.id), "username": "alice", "role": "user", "sid": 999, "jti": "nope",
         "type": "access", "exp": int((utcnow() + timedelta(hours=1)).timestamp())},
        settings.secret_key, algorithm=settings.algorithm,
    )
    assert (await client.get("/auth/me", headers=bearer(token))).status_code == 401


async def test_disabled_user_tokens_stop_working(client, login, make_user, cv):
    tokens = await _tokens(login, make_user, cv)
    async with AsyncSessionLocal() as db:
        from app.models import User
        user = (await db.execute(select(User))).scalars().one()
        user.is_active = False
        await db.commit()
    assert (await client.get("/auth/me", headers=bearer(tokens["access_token"]))).status_code == 401


async def test_request_audit_row_written_after_login(login, make_user, cv):
    """Regression: the request transaction used to stay open until after the
    response, so the audit middleware's own write hit SQLite's lock, waited,
    and was dropped. The middleware row must land."""
    from app.models import AuditLog

    await _tokens(login, make_user, cv)
    async with AsyncSessionLocal() as db:
        actions = (await db.execute(select(AuditLog.action))).scalars().all()
    assert "login_success" in actions
    assert "POST /auth/login" in actions
