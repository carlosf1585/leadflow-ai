import asyncio
import contextlib
import json
import logging

import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.database import engine, Base
from app.api.routes import leads, businesses, billing, webhooks, admin

configure_logging()
log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Scheduler helpers (inline from scheduler/cron.py)
# ---------------------------------------------------------------------------

async def _push(queue: str, payload: dict):
        r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
                    await r.rpush(queue, json.dumps(payload))
        finally:
        await r.close()


async def trigger_discovery():
        for city in settings.DISCOVERY_CITIES:
                    await _push("queue:discovery", {
                                    "action": "discover",
                                    "city": city,
                                    "categories": settings.SERVICE_CATEGORIES,
                    })
                log.info("Discovery cron triggered")


async def trigger_daily_report():
        await _push("queue:analytics", {"action": "daily_report"})


async def trigger_niche_discovery():
        await _push("queue:niche", {"action": "discover_niches"})


async def trigger_sales_sequences():
        await _push("queue:sales", {"action": "run_sequences"})


async def trigger_campaign_check():
        await _push("queue:campaign", {"action": "check_performance"})


async def trigger_campaign_launch():
        for niche in settings.SERVICE_CATEGORIES:
                    await _push("queue:campaign", {
                                    "action": "launch_campaign",
                                    "niche": niche,
                                    "cities": settings.DISCOVERY_CITIES[:3],
                    })
                log.info("Campaign launch cron triggered")


# ---------------------------------------------------------------------------
# Agent runner – starts every agent as a background asyncio task
# ---------------------------------------------------------------------------

_agent_tasks: list[asyncio.Task] = []


async def _start_agents():
        from agents.discovery_agent import DiscoveryAgent
    from agents.outreach_agent import OutreachAgent
    from agents.qualify_agent import QualifyAgent
    from agents.routing_agent import RoutingAgent
    from agents.billing_agent import BillingAgent
    from agents.analytics_agent import AnalyticsAgent
    from agents.niche_agent import NicheAgent
    from agents.sales_agent import SalesAgent
    from agents.landing_agent import LandingAgent
    from agents.campaign_agent import CampaignAgent

    agents = [
                DiscoveryAgent(),
                OutreachAgent(),
                QualifyAgent(),
                RoutingAgent(),
                BillingAgent(),
                AnalyticsAgent(),
                NicheAgent(),
                SalesAgent(),
                LandingAgent(),
                CampaignAgent(),
    ]

    for agent in agents:
                task = asyncio.create_task(agent.run())
                _agent_tasks.append(task)
                log.info("Agent task started", agent=agent.name)


async def _stop_agents():
        for task in _agent_tasks:
                    task.cancel()
                await asyncio.gather(*_agent_tasks, return_exceptions=True)
    _agent_tasks.clear()
    log.info("All agent tasks stopped")


# ---------------------------------------------------------------------------
# FastAPI lifespan – starts DB, agents, and scheduler
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
        log.info("LeadFlow AI starting up", env=settings.ENV)

    # 1. Create DB tables
    async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            log.info("Database tables ready")

    # 2. Start all agents as background tasks
    await _start_agents()

    # 3. Start APScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(trigger_discovery, "cron", hour=2, minute=0)
    scheduler.add_job(trigger_daily_report, "cron", hour=8, minute=0)
    scheduler.add_job(trigger_niche_discovery, "cron", day_of_week="mon", hour=3, minute=0)
    scheduler.add_job(trigger_sales_sequences, "cron", hour=6, minute=0)
    scheduler.add_job(trigger_campaign_check, "cron", hour=10, minute=0)
    scheduler.add_job(trigger_campaign_launch, "cron", hour=4, minute=0)
    scheduler.start()
    log.info("Scheduler started with campaign launch job")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await _stop_agents()
    log.info("LeadFlow AI shutting down")


app = FastAPI(
        title="LeadFlow AI",
        version="3.1.0",
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
        return {"status": "ok", "version": "3.1.0", "agents": len(_agent_tasks)}
