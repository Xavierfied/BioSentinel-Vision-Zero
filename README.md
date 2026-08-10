# AirGapped ZTA — Biometric Auth

Zero-trust biometric authentication system: face-based enroll/login with
liveness detection, JWT sessions, RBAC, an audit-logged request pipeline,
and a local (LM Studio / Gemma) risk engine that scores every session and
can force step-up or lockout. No cloud dependency anywhere in the pipeline.

## Layout

- `biometric_auth/` — FastAPI backend (source root; see below)
- `frontend/` — React + Vite UI

## Backend (`biometric_auth/`)

```
app/
  cv/          face detection (YOLOv8 + RetinaFace step-up), DeepFace
               embeddings, MediaPipe liveness challenges, PAD (anti-spoof)
  auth/        JWT issue/verify, password hashing
  middleware/  audit logging, RBAC, risk scoring
  risk/        Gemma prompt + client (LM Studio, local)
  routers/     enroll, login, heartbeat, admin, demo
  models.py, schemas.py, database.py, main.py
weights/       yolov8n-face.pt, face_landmarker.task
constants.py   thresholds (match, risk, lockout, JWT expiry, LM Studio URL)
```

### Setup

```bash
cd biometric_auth
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Requires an LM Studio (or compatible) server at `LM_STUDIO_URL` in
`constants.py` for risk scoring; the engine falls back to a neutral score of
50 if it's unreachable, so the API still runs without it.

### API surface

| Router | Route | Purpose |
|---|---|---|
| enroll | `POST /enroll/` | liveness → face detect → embedding → create user |
| login | `POST /auth/login` | password + liveness + face match → JWT pair |
| heartbeat | `POST /heartbeat` | mid-session face recheck, feeds risk engine |
| admin | `POST /admin/unblock/{user_id}` | admin-only, lifts a lockout |
| demo | `POST /demo/*` | inject synthetic risk signals for the risk engine |

## Frontend (`frontend/`)

```bash
cd frontend
npm install
npm run dev        # port 3000, proxies /enroll, /auth, /heartbeat, /admin to :8000
```

- `pages/Enroll.jsx`, `pages/Login.jsx` — real flows against the FastAPI backend
- `components/LivenessCamera.jsx` — shared MediaPipe FaceMesh capture, two
  sequential challenges (blink/turn) with a hard timeout
- `context/AuthContext.jsx` — JWT held in memory only, never localStorage
- `pages/demo/*` and `pages/DemoShowcase.jsx` — **scripted, fake** walkthroughs
  (setTimeout timelines, canned JSON, no backend calls) for presenting the
  concept. Not part of the real auth path — see below.

---

## What's left

### Backend

- **PAD is advisory-only** (`app/cv/pad.py`, `PAD_HARD_BLOCK = False`).
  Thresholds (`TEXTURE_MIN_LAP_VAR`, `SPECULAR_MAX_RATIO`, `BLOCK_CV_MIN`)
  were set blind and were flagging real webcam frames. It currently just
  logs signal values at WARNING. Needs calibration against real captured
  frames before it can block anything.
- **Head-turn liveness threshold is unresolved.** Last tuning pass
  (`TURN_LEFT_THRESHOLD`/`TURN_RIGHT_THRESHOLD` in `constants.py` and
  mirrored in `LivenessCamera.jsx`) made it worse, not better — turn
  detection fires on minor drift. Needs live testing with logged EAR/turn
  offset values to pick real thresholds, not another blind guess.
  liveness.py / LivenessCamera.jsx.
- **No automated test suite.** All QA so far (`copilot_QA`) was manual,
  ad-hoc `python -c "..."` smoke checks — no `pytest` files exist despite
  `pytest`/`pytest-asyncio` being in `requirements.txt`. Needs real
  `tests/` covering enroll/login/heartbeat pipelines, JWT, RBAC, and risk
  middleware, so regressions (like the PAD/lockout bug already hit once)
  get caught before manual testing.
- **`SECRET_KEY` is hardcoded in `constants.py`** and committed to git.
  Needs to move to an environment variable before this goes anywhere near
  a real deployment.
- **No Alembic migrations** — schema changes currently mean deleting the
  `.db` file. Fine for demo scope, a real blocker once there's data worth
  keeping.
- **`tmp_reset_user.py`** is a standalone manual unlock script, not an
  admin API path — worth folding into `/admin` or deleting once the admin
  UI can do it.
- Enroll/login routers write `AuditLog` rows with `ip=None` (only
  `AuditMiddleware` captures real client IP), so Gemma never sees IP
  history for the auth events themselves — only for everything after.

### Frontend

- **`Dashboard.jsx` is a placeholder** (`"coming in next commit"`) — the
  page a real logged-in user lands on after `/auth/login` does nothing yet.
  This is the actual gap for real testing: there's no authenticated view to
  show session state, trigger `/heartbeat`, display the live risk score, or
  log out.
- **No real admin UI.** `/admin/unblock/{user_id}` only exists as an API
  call; `pages/demo/DemoAdmin.jsx` is a scripted fake with a hardcoded
  table and a `setTimeout`-simulated click, not a real unblock request.
- **The `/demo` routes are not real testing surfaces.** `DemoShowcase.jsx`
  and everything under `pages/demo/` run entirely on local component state
  and timers — no `fetch` calls, no webcam-driven MediaPipe results feeding
  real logic (aside from a cosmetic FaceMesh overlay in `DemoShowcase`).
  They're a presentation/pitch tool, not a QA path, and shouldn't be used
  to judge whether the real pipeline works.
- To actually exercise the system end to end: finish `Dashboard.jsx` (call
  `/heartbeat` on an interval, show risk score + session state, logout),
  then test the real `/enroll` → `/login` → `/dashboard` path in a browser
  with a real webcam — not the `/demo` routes.
