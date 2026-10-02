import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_tables
from app.middleware.audit import AuditMiddleware
from app.middleware.risk import RiskMiddleware
from app.routers.enroll import router as enroll_router
from app.routers.login import router as login_router
from app.routers.heartbeat import router as heartbeat_router
from app.routers.admin import router as admin_router
from app.security.uploads import BodySizeLimitMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        logger.info("AUTO_CREATE_TABLES is on — creating tables with create_all()")
        await create_tables()
    else:
        logger.info("Database schema is managed by Alembic (alembic upgrade head)")
    if settings.demo_mode:
        logger.warning("DEMO_MODE is on: /demo endpoints can inject fake risk signals")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AirGapped ZTA — Biometric Auth",
    description="Zero-trust biometric authentication "
                "with local AI risk scoring",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# FastAPI runs middleware in reverse registration order.
# AuditMiddleware must run first (attach user to state).
# RiskMiddleware runs second (reads user, scores, acts).
# So RiskMiddleware is registered first, AuditMiddleware second.
app.add_middleware(RiskMiddleware)
app.add_middleware(AuditMiddleware)
# Registered last so it runs first: oversized bodies are refused before any
# other middleware or the multipart parser touches them.
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

# Only mount if the directory exists — the frontend is built
# in a later commit and is not present yet.
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

app.include_router(enroll_router)
app.include_router(login_router)
app.include_router(heartbeat_router)
app.include_router(admin_router)

if settings.demo_mode:
    from app.routers.demo import router as demo_router

    app.include_router(demo_router)


@app.get("/health", tags=["system"])
async def health_check():
    return {
        "status": "ok",
        "service": "AirGapped ZTA Biometric Auth",
        "version": "1.0.0",
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "message": "AirGapped ZTA API",
        "docs": "/docs",
        "health": "/health",
    }
