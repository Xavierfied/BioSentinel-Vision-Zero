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

