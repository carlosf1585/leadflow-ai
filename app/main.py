import asyncio
import contextlib
import logging

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.database import engine, Base
from app.api.routes import leads, businesses, billing, webhooks, admin

configure_logging()
log = structlog.get_logger()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("LeadFlow AI starting up", env=settings.ENV)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables ready")
    yield
    log.info("LeadFlow AI shutting down")


app = FastAPI(
    title="LeadFlow AI",
    version="3.0.0",
    description="Automated AI-powered lead generation SaaS platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("Unhandled exception", path=request.url.path, error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(businesses.router, prefix="/api/businesses", tags=["businesses"])
app.include_router(billing.router, prefix="/api/billing", tags=["billing"])
app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "3.0.0"}
