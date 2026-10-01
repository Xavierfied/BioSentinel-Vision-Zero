"""Password-first login, timed lockout and account enumeration."""

from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import AuditLog, User
from app.timeutil import as_utc, utcnow
from tests.conftest import STRANGER, bearer


async def _user(username="alice"):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User).where(User.username == username))).scalars().one()


async def test_wrong_password_and_unknown_user_look_the_same(login, make_user, cv):
    await make_user()
    wrong = await login(password="nope-nope-nope")
    unknown = await login(username="nobody")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "Invalid credentials"}


async def test_failures_lock_temporarily_not_permanently(login, make_user, cv):
    await make_user()
    for _ in range(settings.max_failed_login_attempts):
        resp = await login(password="nope-nope-nope")
        assert resp.json() == {"detail": "Invalid credentials"}

    user = await _user()
    assert user.is_active is True, "failed logins must not disable the account"
    assert user.lock_count == 1
    remaining = as_utc(user.locked_until) - utcnow()
    assert timedelta(seconds=0) < remaining <= timedelta(minutes=settings.lockout_backoff_minutes[0])

    # Right password during the lock: told it is locked, with Retry-After.
    locked = await login()
    assert locked.status_code == 403
    assert "temporarily locked" in locked.json()["detail"]
    assert int(locked.headers["Retry-After"]) > 0


async def test_wrong_password_during_lock_does_not_extend_it(login, make_user, cv):
    await make_user()
    for _ in range(settings.max_failed_login_attempts):
        await login(password="nope-nope-nope")
    first_until = (await _user()).locked_until
    for _ in range(5):
        await login(password="nope-nope-nope")
    user = await _user()
    assert user.locked_until == first_until
    assert user.lock_count == 1


async def test_backoff_grows_with_repeat_locks(login, make_user, cv):
    await make_user()
    for lock in range(1, 3):
        async with AsyncSessionLocal() as db:
            user = (await db.execute(select(User))).scalars().one()
            user.locked_until = None  # let the previous lock lapse
            await db.commit()
        for _ in range(settings.max_failed_login_attempts):
            await login(password="nope-nope-nope")
        user = await _user()
        assert user.lock_count == lock
        expected = settings.lockout_backoff_minutes[lock - 1]
        remaining = (as_utc(user.locked_until) - utcnow()).total_seconds() / 60
        assert expected - 1 < remaining <= expected


async def test_expired_lock_allows_login_and_success_resets(login, make_user, cv):
    await make_user(
        locked_until=utcnow() - timedelta(seconds=1), lock_count=2, failed_streak=1,
    )
    resp = await login()
    assert resp.status_code == 200
    user = await _user()
    assert (user.failed_streak, user.lock_count, user.locked_until) == (0, 0, None)


async def test_face_mismatch_counts_toward_lock(login, make_user, cv):
    await make_user()
    cv.embedding = STRANGER
    statuses = [(await login()).status_code for _ in range(settings.max_failed_login_attempts)]
    assert statuses[:-1] == [401] * (len(statuses) - 1)
    assert statuses[-1] == 403  # the attempt that triggers the lock says so
    async with AsyncSessionLocal() as db:
        codes = (await db.execute(select(AuditLog.reason_code).where(AuditLog.action == "login_failed"))).scalars().all()
    assert set(codes) == {"face_mismatch"}


async def test_admin_unblock_clears_lock_and_sessions(client, login, make_user, cv):
    await make_user(username="root", role="admin")
    await make_user(username="bob")
    admin_tokens = (await login(username="root")).json()
    bob_tokens = (await login(username="bob")).json()
    for _ in range(settings.max_failed_login_attempts):
        await login(username="bob", password="nope-nope-nope")

    bob = await _user("bob")
    resp = await client.post(f"/admin/unblock/{bob.id}", headers=bearer(admin_tokens["access_token"]))
    assert resp.status_code == 200
    bob = await _user("bob")
    assert bob.locked_until is None and bob.lock_count == 0
    assert (await client.get("/auth/me", headers=bearer(bob_tokens["access_token"]))).status_code == 401


async def test_non_admin_cannot_unblock(client, login, make_user, cv):
    await make_user()
    tokens = (await login()).json()
    resp = await client.post("/admin/unblock/1", headers=bearer(tokens["access_token"]))
    assert resp.status_code == 403
