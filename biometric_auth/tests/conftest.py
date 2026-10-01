"""Test setup: settings from the environment, CV libraries stubbed out.

The API tests exercise auth logic, not the models, so ultralytics, DeepFace,
RetinaFace and MediaPipe are replaced with stub modules before the app is
imported. Individual tests patch the CV functions the routers call.
"""

import os
import secrets
import sys
import tempfile
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

_TMP = tempfile.mkdtemp(prefix="biosentinel-tests-")
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["DEMO_MODE"] = "false"
os.environ["MAX_REQUEST_BYTES"] = str(256 * 1024)
os.environ["LOGIN_RATE_LIMIT_PER_MINUTE"] = "50"


def _stub(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


for _name in ("ultralytics", "deepface", "retinaface"):
    if _name not in sys.modules:
        _stub(_name, YOLO=MagicMock(), DeepFace=MagicMock(), RetinaFace=MagicMock())
if "mediapipe" not in sys.modules:
    _stub("mediapipe", Image=MagicMock(), ImageFormat=MagicMock())
    _stub("mediapipe.tasks")
    _stub("mediapipe.tasks.python", BaseOptions=MagicMock())
    _stub(
        "mediapipe.tasks.python.vision",
        FaceLandmarker=MagicMock(),
        FaceLandmarkerOptions=MagicMock(),
        RunningMode=MagicMock(),
    )

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.auth.jwt_service import hash_password, pwd_context  # noqa: E402
from app.database import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.routers import login as login_router  # noqa: E402
from app.security.ratelimit import limiter  # noqa: E402

# Cheap bcrypt in tests; production keeps passlib's default cost.
pwd_context.update(bcrypt__rounds=4)

ENROLLED = np.ones(128, dtype=np.float32)
STRANGER = np.concatenate([np.ones(64), -np.ones(64)]).astype(np.float32)
PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    limiter.reset()
    yield


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def jpeg() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.full((64, 64, 3), 128, dtype=np.uint8))
    assert ok
    return buf.tobytes()


@pytest.fixture
def make_user():
    async def _make(username="alice", password=PASSWORD, role="user", **fields):
        async with AsyncSessionLocal() as db:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password=hash_password(password),
                face_embedding="[" + ",".join(["1.0"] * 128) + "]",
                role=role,
                is_active=True,
                **fields,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

    return _make


@pytest.fixture
def cv(monkeypatch):
    """Make the CV pipeline pass; tests can change ``cv.embedding``."""
    state = SimpleNamespace(embedding=ENROLLED, liveness=(True, "Challenge passed"))
    face = SimpleNamespace(face_crop=np.zeros((112, 112, 3), dtype=np.uint8))
    monkeypatch.setattr(login_router, "verify_challenge_frame", lambda frame, ch: state.liveness)
    monkeypatch.setattr(login_router, "step_up_detector", SimpleNamespace(detect=lambda frame: face))
    monkeypatch.setattr(login_router, "check_presentation_attack", lambda crop: (False, "ok"))
    monkeypatch.setattr(login_router, "extract_embedding", lambda crop: state.embedding)
    return state


@pytest.fixture
def login(client, jpeg):
    async def _login(username="alice", password=PASSWORD, image=None):
        return await client.post(
            "/auth/login",
            data={"username": username, "password": password},
            files={"image": ("frame.jpg", image if image is not None else jpeg, "image/jpeg")},
        )

    return _login


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
