import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import create_tables
from app.middleware.audit import AuditMiddleware
from app.middleware.risk import RiskMiddleware
from app.routers.enroll import router as enroll_router
from app.routers.login import router as login_router
from app.routers.heartbeat import router as heartbeat_router
from app.routers.admin import router as admin_router
from app.routers.demo import router as demo_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up — creating database tables")
    await create_tables()
    logger.info("Database ready")
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
    allow_origins=["http://localhost:3000",
                   "http://127.0.0.1:3000",
                   "http://localhost:8000",
                   "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# FastAPI runs middleware in reverse registration order.
# AuditMiddleware must run first (attach user to state).
# RiskMiddleware runs second (reads user, scores, acts).
# So RiskMiddleware is registered first, AuditMiddleware second.
app.add_middleware(RiskMiddleware)
app.add_middleware(AuditMiddleware)

# Only mount if the directory exists — the frontend is built
# in a later commit and is not present yet.
static_path = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_path):
    app.mount("/static", StaticFiles(directory=static_path), name="static")

app.include_router(enroll_router)
app.include_router(login_router)
app.include_router(heartbeat_router)
app.include_router(admin_router)
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
