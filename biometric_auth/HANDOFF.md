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

**Next:** Commit #3 — YOLOv8 face detector with confidence threshold