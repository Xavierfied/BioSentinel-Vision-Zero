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
app/config.py  all settings, read from environment variables / .env
migrations/    Alembic migrations (SQLite now, PostgreSQL-ready)
tests/         pytest suite (CV libraries stubbed, runs in seconds)
```

### Setup

```bash
cd biometric_auth
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env      # then set SECRET_KEY (the app will not start without it)
python -c "import secrets; print(secrets.token_urlsafe(48))"

alembic upgrade head        # create / update the database schema
uvicorn app.main:app --reload
```

Already have a `biometric_auth.db` from before migrations existed? Mark it
first, then upgrade: `alembic stamp 0001_baseline && alembic upgrade head`.
Existing sessions are dropped by the upgrade, so everyone logs in again.

Switching to PostgreSQL later: see [docs/POSTGRES.md](biometric_auth/docs/POSTGRES.md).

Tests: `pip install -r requirements-test.txt && python -m pytest -q`.

Requires an LM Studio (or compatible) server at `LM_STUDIO_URL` for risk
scoring; the engine falls back to a neutral score of 50 if it's unreachable,
so the API still runs without it.

### API surface

| Router | Route | Purpose |
|---|---|---|
| enroll | `POST /enroll/` | liveness → face detect → embedding → create user |
| login | `POST /auth/login` | password + liveness + face match → JWT pair (opens a server-side session) |
| login | `POST /auth/refresh` | swap a refresh token for a new pair (each refresh token works once) |
| login | `POST /auth/logout` | revoke the caller's session |
| login | `GET /auth/me` | the caller's profile |
| heartbeat | `POST /heartbeat` | mid-session face recheck, feeds risk engine |
| admin | `POST /admin/unblock/{user_id}` | admin-only, lifts a lockout and revokes the user's sessions |
| demo | `POST /demo/*` | inject synthetic risk signals; only mounted when `DEMO_MODE=true` |

Security behaviour worth knowing:

- Tokens are tied to a `sessions` row and checked on every request, so
  logout, step-up and lockout end a session immediately. Only token ids and
  hashes are stored, never the tokens.
- Failed logins lock the account for 1, 5, then 15 minutes
  (`LOCKOUT_BACKOFF_MINUTES`), not permanently. Wrong passwords and unknown
  usernames get the same response, so accounts can't be discovered.
- `/auth/login`, `/auth/refresh` and `/enroll/` are rate-limited per IP.
  Request bodies over 4 MB and non-JPEG frames are refused.
- `X-Forwarded-For` is only trusted from `TRUSTED_PROXIES`.

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
  (`TURN_LEFT_THRESHOLD`/`TURN_RIGHT_THRESHOLD` in `app/cv/liveness.py` and
  mirrored in `LivenessCamera.jsx`) made it worse, not better — turn
  detection fires on minor drift. Needs live testing with logged EAR/turn
  offset values to pick real thresholds, not another blind guess.
  liveness.py / LivenessCamera.jsx.
- **Tests cover auth, sessions, lockout and hardening, not the CV
  pipeline.** The CV models are stubbed in `tests/`. Liveness, PAD and
  matching need recorded clips and a calibration run (next phase).
- **Liveness is still one frame chosen by the client.** The next phase moves
  it to server-issued challenges verified over a short clip.
- **The old `SECRET_KEY` is in git history.** It is no longer used anywhere,
  but treat it as public: never reuse it.

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
