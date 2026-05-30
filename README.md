# Biometric Auth

Minimal backend components for a biometric authentication service. This repository currently contains data models, database wiring, and request/response schemas.

## Project Layout

- app/: application package (database, models, schemas)
- constants.py: shared constants
- requirements.txt: Python dependencies
- HANDOFF.md: current status and notes

## Setup

1) Create and activate a virtual environment.
2) Install dependencies:

   pip install -r requirements.txt

## Quick Checks

Run basic schema checks from the project root:

python -c "
from app.schemas import (
    UserCreate, UserOut, SessionOut,
    AuditLogOut, TokenResponse, LoginRequest, EnrollRequest
)
from app.database import get_db
import inspect

u = UserCreate(username='testuser', email='test@example.com', password='password123')
print('UserCreate OK:', u)

t = TokenResponse(access_token='abc', refresh_token='xyz', expires_in=1800)
print('TokenResponse OK:', t)

l = LoginRequest(username='testuser', password='password123')
print('LoginRequest OK:', l)

print('get_db is async generator:', inspect.isasyncgenfunction(get_db))
print('All schema checks passed.')
"

## Notes

- Database file is created locally during development (ignored by git).
- See HANDOFF.md for current progress and next steps.
