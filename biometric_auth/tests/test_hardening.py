"""Rate limits, upload limits, proxy headers, demo gating and config."""

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.config import Settings, settings
from app.security import net
from tests.conftest import PASSWORD


async def test_login_rate_limited_per_ip(login, make_user, cv, monkeypatch):
    monkeypatch.setattr(settings, "login_rate_limit_per_minute", 3)
    await make_user()
    codes = [(await login(username="nobody")).status_code for _ in range(4)]
    assert codes == [401, 401, 401, 429]
    blocked = await login()
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


async def test_oversized_body_rejected(login, make_user, cv):
    await make_user()
    huge = b"\xff\xd8\xff" + b"\0" * (settings.max_request_bytes + 10)
    resp = await login(image=huge)
    assert resp.status_code == 413


async def test_non_jpeg_rejected(login, make_user, cv):
    await make_user()
    resp = await login(image=b"\x89PNG\r\n\x1a\n" + b"\0" * 100)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Image must be a JPEG"


async def test_demo_routes_absent_by_default(client):
    resp = await client.post("/demo/reset-signals", params={"user_id": 1})
    assert resp.status_code == 404


def _request(peer: str, xff: str) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "headers": [(b"x-forwarded-for", xff.encode())],
        "client": (peer, 1234),
    })


def test_forwarded_for_ignored_from_untrusted_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", [])
    assert net.get_client_ip(_request("203.0.113.9", "1.2.3.4")) == "203.0.113.9"


def test_forwarded_for_used_behind_trusted_proxy(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["10.0.0.2"])
    assert net.get_client_ip(_request("10.0.0.2", "1.2.3.4, 10.0.0.2")) == "1.2.3.4"


def test_settings_require_a_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_short_secret_key(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "too-short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_list_settings_parse_from_env(monkeypatch):
    monkeypatch.setenv("LOCKOUT_BACKOFF_MINUTES", "2,10")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.2, 10.0.0.3")
    parsed = Settings(_env_file=None)
    assert parsed.lockout_backoff_minutes == [2, 10]
    assert parsed.trusted_proxies == ["10.0.0.2", "10.0.0.3"]


async def test_enroll_validates_fields(client, jpeg):
    resp = await client.post(
        "/enroll/",
        data={"username": "x", "email": "not-an-email", "password": "short"},
        files={"image": ("frame.jpg", jpeg, "image/jpeg")},
    )
    assert resp.status_code == 422
    fields = {item["field"] for item in resp.json()["detail"]}
    assert fields == {"username", "email", "password"}


async def test_enroll_rejects_duplicate_email(client, jpeg, make_user):
    await make_user()
    resp = await client.post(
        "/enroll/",
        data={"username": "alice2", "email": "alice@example.com", "password": PASSWORD},
        files={"image": ("frame.jpg", jpeg, "image/jpeg")},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Email already registered"
