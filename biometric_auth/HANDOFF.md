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

