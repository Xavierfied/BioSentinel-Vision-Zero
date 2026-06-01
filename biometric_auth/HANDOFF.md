# HANDOFF.md

## Project: Biometric Authentication System
FastAPI backend with YOLOv8 face detection, DeepFace embeddings,
Gemma-based local risk engine, JWT auth, RBAC, and audit logging.
Zero cloud dependency for risk scoring.

---

## Commit Log

### #1 feat(db): add SQLAlchemy models for User, Session, AuditLog
**Hash:** [paste hash here]
**What was built:**
- Project folder scaffolded
- constants.py with all system-wide thresholds
- app/database.py: async SQLAlchemy engine, AsyncSession, Base, create_tables()
- app/models.py: User (with face_embedding as JSON text), Session, AuditLog
- requirements.txt with full dependency list

**Why:**
All future services (auth, CV, risk engine) depend on these models.
SQLite + create_all() used intentionally — no Alembic needed for demo scope.

**Tested:**
create_tables() ran cleanly, .db file created, all three tables queryable.

---

### #2 feat(db): add Pydantic schemas and async get_db dependency
**Hash:** [paste hash here]
**What was built:**
- app/schemas.py: UserCreate, UserOut, SessionOut, AuditLogOut,
  TokenResponse, LoginRequest, EnrollRequest (all Pydantic v2)
- app/database.py: get_db async generator with commit/rollback/close

**Why:**
Schemas are the contract between HTTP layer and business logic.
get_db is the FastAPI dependency all routers will use to get a 
scoped DB session that auto-commits on success and rolls back on error.

**Tested:**
All schemas instantiate correctly, get_db confirmed as async generator,
Pydantic v2 validation works on UserCreate fields.

---

### #3 feat(cv): implement YOLOv8 face detector with confidence threshold
**Hash:** [paste hash here]
**What was built:**
- app/cv/__init__.py (empty, marks cv as a package)
- app/cv/detector.py:
  - FaceDetection dataclass (bbox, confidence, face_crop)
  - FaceDetector class with lazy model loading (singleton)
  - detect() — returns all faces above FACE_CONFIDENCE_THRESHOLD
  - detect_best() — returns highest confidence face or None
  - module-level face_detector singleton instance

**Why:**
YOLOv8 is the first pass detector. It is fast but can miss faces
at odd angles or low light. Low-confidence detections will be
escalated to RetinaFace in commit #5 (step-up strategy).
Lazy loading prevents the heavy YOLO model from blocking app startup.
FACE_CONFIDENCE_THRESHOLD = 0.75 comes from constants.py.

**Tested:**
Blank image returns empty list, detect_best returns None,
to_dict() excludes face_crop numpy array, model lazy loads cleanly.

---

### #4 feat(auth): implement JWT access and refresh token service
**Hash:** [paste hash here]
**What was built:**
- app/auth/__init__.py (empty)
- app/auth/jwt_service.py:
  - hash_password / verify_password (bcrypt via passlib)
  - create_access_token / create_refresh_token (python-jose)
  - decode_token — returns None on failure, never raises
  - create_token_pair — single call to get both tokens
  - save_session — persists token pair to DB (no commit, get_db handles it)
  - revoke_session — marks session is_revoked=True
  - get_user_by_username — active user lookup by username

**Why:**
All auth flows (enroll, login, protected routes) need tokens.
Keeping this as pure functions (no class) makes it easy to import
one function at a time in routers and middleware.
decode_token returns None instead of raising so middleware
can handle invalid tokens gracefully without try/except everywhere.

**Tested:**
Hash/verify, encode/decode, token type field, tampered token → None,
token pair tuple all confirmed passing.

---

### #5 feat(cv): add RetinaFace step-up for low-confidence detections
**Hash:** [paste hash here]
**What was built:**
- app/cv/stepup.py:
  - StepUpDetector class with detect() and _retinaface_detect()
  - detect() tries YOLO first, escalates to RetinaFace only on failure
  - _retinaface_detect() parses RetinaFace dict output into FaceDetection
  - Guards against RetinaFace returning int (not dict) when no face found
  - step_up_detector module-level singleton

**Why:**
YOLO is fast but misses faces in bad lighting or at angles.
RetinaFace is purpose-built for faces and more robust, but slower.
The two-stage pattern keeps the happy path (good lighting) fast
and only pays the RetinaFace cost when YOLO is uncertain.
All downstream code (DeepFace in commit #6) imports step_up_detector,
not face_detector directly — so the escalation is transparent.

**Tested:**
Blank image returns None through both stages, singleton type confirmed,
no circular imports, RetinaFace int-return edge case handled.

---

### #6 feat(cv): integrate DeepFace embeddings, cosine similarity, anti-spoofing
**Hash:** [paste hash here]
**What was built:**
- app/cv/embeddings.py:
  - extract_embedding() — DeepFace.represent() with anti_spoofing=True, Facenet model
  - embedding_to_json() / json_to_embedding() — serialisation for DB storage
  - compute_similarity() — cosine similarity, zero-vector guarded
  - is_match() — returns (bool, float) so Gemma always gets the raw score

**Why:**
anti_spoofing=True makes DeepFace check texture/reflection for photo attacks.
enforce_detection=False is intentional — face was already confirmed by the CV
cascade (YOLO/RetinaFace). is_match() returns the raw score alongside the bool
because Gemma needs it as the face_similarity signal in the risk engine.
embedding_to_json/json_to_embedding handle the User.face_embedding DB field.

**Tested:**
Cosine similarity math verified (identical=1.0, orthogonal=0.0), zero vector
guard, is_match threshold, JSON round-trip, graceful None on bad input and blank image.

---

### #7 feat(cv): implement MediaPipe liveness challenge (blink/turn)
**Hash:** [paste hash here]
**What was built:**
- app/cv/liveness.py: ChallengeType enum, LivenessChallenge dataclass,
  get_random_challenge(), _eye_aspect_ratio(), _detect_blink(),
  _detect_head_turn(), verify_challenge_frame()
- weights/face_landmarker.task: 3.76MB Tasks API model
- requirements.txt: added mediapipe==0.10.35

**Why:**
Legacy mp.solutions.face_mesh API removed from mediapipe ≥0.10.22.
Versions that have it (≤0.10.21) pin protobuf<5 which breaks TF 2.21
and DeepFace (need protobuf ≥6.x). Irreconcilable conflict — verified
empirically. Switched to Tasks API (FaceLandmarker). All liveness logic
(EAR, blink threshold 0.20, head turn offsets 0.65/0.35, landmark
indices) is identical — only the FaceMesh call site changed.
MediaPipe used for landmarks ONLY, not identity (per project rules).

**Tested:**
16/16 smoke tests passed. Stack confirmed intact: TF 2.21, DeepFace,
numpy 2.4.6, protobuf 7.35.0, opencv 4.13 all unaffected.

---

### #8 feat(middleware): add RBAC role enforcement and require_role dependency
**Hash:** [paste hash here]
**What was built:**
- app/middleware/__init__.py (empty)
- app/middleware/rbac.py:
  - get_current_user() — validates JWT, fetches User from DB,
    checks is_active
  - require_role(*roles) — factory that returns a FastAPI
    dependency; raises 403 if user role not in allowed roles

**Why:**
Every admin and demo endpoint needs role protection. Using a
factory pattern (require_role returns a dependency) means
protection is a one-liner on any route: 
Depends(require_role("admin")). No role logic scattered across
routers. get_current_user is also exported so non-role-restricted
routes can still identify who is calling.

**Tested:**
Factory returns callable, correct role passes, wrong role 403,
multi-role acceptance, invalid token 401 confirmed.

---

### #9 feat(middleware): implement AuditLog middleware and JWT validation
**Hash:** [paste hash here]
**What was built:**
- app/middleware/audit.py:
  - AuditMiddleware(BaseHTTPMiddleware) — wraps every request
  - dispatch() — decodes JWT into request.state, calls route,
    writes AuditLog after response
  - _write_audit_log() — opens its own AsyncSessionLocal session
    (not get_db — middleware is outside FastAPI DI lifecycle)
  - _get_client_ip() — X-Forwarded-For aware, falls back to
    client.host, then "unknown"
  - SKIP_LOGGING_PATHS — docs/openapi routes not logged

**Why:**
AuditLog rows are the data source for Gemma's risk signals
(failed_attempts_today, actions_per_minute, ip history).
Without this middleware writing every request, the risk engine
has nothing to query. request.state.user_id lets all routers
identify the caller without re-decoding the JWT themselves.
_write_audit_log uses its own session because middleware runs
outside the request-scoped get_db lifecycle — using Depends()
in middleware causes runtime errors.

**Tested:**
IP extraction (X-Forwarded-For, host fallback, unknown),
valid JWT populates state, invalid JWT sets state to None,
risk_score placeholder attached, module imports cleanly.

---

### #10 feat(risk): build Gemma risk engine with structured JSON output
**Hash:** [paste hash here]
**What was built:**
- app/risk/__init__.py (empty)
- app/risk/engine.py:
  - build_signal_dict() — typed constructor for signal dict
  - build_prompt() — builds Gemma prompt with signals +
    JSON-only instruction
  - query_gemma() — async httpx POST to LM Studio, strips
    markdown fences, parses JSON
  - validate_score() — clamps to [0,100], falls back to 50.0
  - evaluate_risk() — orchestrates all above, returns
    (float, str) tuple

**Why:**
Gemma receives only behavioral signals as plain text —
never images, embeddings, or secrets (per project rules).
Falls back to 50.0 (neutral) on any failure so a Gemma
outage never crashes the app or locks users out.
markdown fence stripping handles Gemma occasionally wrapping
JSON in backticks despite instructions.
evaluate_risk returns a tuple so callers always get both
the score (for threshold checks) and the reason
(for AuditLog.meta).

**Tested:**
signal dict keys, prompt content, score validation (happy
path + bad values + missing key), fallback on None,
markdown fence stripping, evaluate_risk with mock Gemma.

---

### #11 feat(middleware): add RiskMiddleware injecting risk score into request state
**Hash:** [paste hash here]
**What was built:**
- app/middleware/risk.py:
  - RiskMiddleware(BaseHTTPMiddleware) — activates on RISK_CHECK_PATHS
  - dispatch() — runs route first, then scores, then acts on result
  - _assemble_signals() — queries AuditLog for IP change, failed
    attempts, actions/min, session age; builds signal dict for Gemma
  - _handle_stepup() — revokes all active sessions for user
  - _handle_lockout() — sets is_active=False + revokes all sessions

**Why:**
Middleware runs AFTER call_next so the heartbeat router can set
request.state.face_similarity before Gemma is called.
Opens its own AsyncSessionLocal sessions (no Depends() in middleware).
Any exception falls back to returning the original response —
a Gemma outage or DB hiccup never locks users out or crashes the app.
request.state.risk_score is set before returning so AuditMiddleware
(commit #9) picks it up and writes it to AuditLog.

**Tested:**
Skip non-risk paths, skip unauthenticated requests, safe score
injects to state, step-up returns 401, lockout returns 403,
exception safety confirmed.

---

### #12 feat(router): add /enroll endpoint with full biometric pipeline
**Hash:** [paste hash here]
**What was built:**
- app/routers/__init__.py (empty)
- app/routers/enroll.py:
  - POST /enroll/ — 8-step pipeline: username check →
    image decode → liveness → face detect → embedding
    → user create → audit log → return UserOut
  - _decode_image() — PIL bytes → BGR numpy array
  - Uses Form() + UploadFile for multipart submissions
  - db.flush() after User creation to get ID before
    AuditLog write; no explicit commit (get_db handles it)

**Why:**
Enrollment is the only way users enter the system.
face_embedding stored as JSON in User.face_embedding
is the permanent identity ground truth — every future
login and heartbeat compares against this.
Liveness check runs on enrollment too so attackers
cannot enroll using someone else's photo.
All CV steps return None on failure so errors map
cleanly to HTTP 400s with specific messages.

**Tested:**
Router imports cleanly, _decode_image shape and error
handling, route registration confirmed, mock pipeline
flow verified end-to-end.

---

### #13 feat(router): add /login endpoint with 2FA and attempt tracking
**Hash:** [paste hash here]
**What was built:**
- app/routers/login.py:
  - POST /auth/login — 12-step pipeline: user fetch →
    active check → attempt count → password → image
    decode → liveness → face detect → embedding →
    similarity → JWT issue → audit → return tokens
  - _count_recent_failures() — counts login_failed
    AuditLog entries today for this user
  - _write_audit() — shared helper for audit entries
    within the login transaction

**Why:**
Every failure path writes an AuditLog entry with a
specific reason — Gemma queries these in commit #11.
Attempt counter checked BEFORE password verify to
prevent timing attacks from revealing whether the
account exists. is_active=False set inline when
lockout threshold hit so it takes effect immediately
in the same transaction. HTTPException re-raised
before the generic 500 handler (same pattern as
enroll.py) so specific 401/403 messages are preserved.

**Tested:**
Unit: wrong password 401 with remaining count,
locked account 403, unknown user 401.
Manual: full enroll→login curl flow, attempt counter
increments, account locks at 3 failures, AuditLog
rows verified in DB directly, JWT payload verified
at jwt.io.

---

### #14 feat(router): add /heartbeat, /admin, /demo endpoints
**Hash:** [paste hash here]
**What was built:**
- app/routers/heartbeat.py:
  - POST /heartbeat — decodes image, runs CV pipeline,
    sets request.state.face_similarity for RiskMiddleware
  - No face → similarity=0.0, returns status not 400
    (missing face during session is a risk signal not an error)
- app/routers/admin.py:
  - POST /admin/unblock/{user_id} — admin only,
    sets is_active=True, revokes existing sessions
- app/routers/demo.py:
  - POST /demo/trigger-ip-shift — injects mismatched IPs
  - POST /demo/spam-requests — writes 20 rapid audit rows
  - POST /demo/reset-signals — cleans up demo entries
  All three use AsyncSessionLocal directly (not get_db)
  per lesson from commit #13 rollback issue.

**Why:**
Heartbeat returns 200 always (even no-face) because
RiskMiddleware intercepts and overrides with 401/403
based on the score — the route itself should not decide.
face_similarity=0.0 on no-face is a strong Gemma signal.
Demo triggers write to AuditLog using the same fields
_assemble_signals() reads, so Gemma sees real signal
spikes without needing to wait for actual events.

**Tested:**
Unit: all routes registered, no-face sets similarity 0.0,
matched face sets correct similarity on request.state.
Manual: heartbeat flow with real JWT, admin unblock,
demo trigger→heartbeat→reset cycle confirmed.

---

### #15 feat(app): wire all routers and middleware in main.py with lifespan
**Hash:** [paste hash here]
**What was built:**
- app/main.py:
  - lifespan() — creates DB tables on startup
  - FastAPI app with title, description, version
  - CORSMiddleware for localhost origins
  - RiskMiddleware registered before AuditMiddleware
    (FastAPI reverses order — Audit runs first)
  - All 5 routers included
  - Static files mounted conditionally (only if
    app/static/ exists — frontend not built yet)
  - /health and / endpoints for system checks

**Why:**
Middleware registration ORDER is critical.
AuditMiddleware must attach request.state.user_id
before RiskMiddleware reads it. FastAPI reverses
add_middleware() order at runtime, so Risk is
added first, Audit second — this ensures Audit
runs first on the way in, Risk runs last on
the way out (after route sets face_similarity).
Lifespan replaces deprecated @app.on_event so
the app is forward-compatible with FastAPI 0.100+.

**Tested:**
/health 200, / 200, all 9 routes present in
route table, both middleware confirmed registered,
full enroll→login→heartbeat chain on live server,
DB AuditLog entries verified after each step.