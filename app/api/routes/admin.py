import json
from datetime import datetime, timedelta, timezone
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import require_admin
from app.db.database import get_db
from app.db.models import AgentLog
from app.db.repositories.analytics_repo import AnalyticsRepository
log = structlog.get_logger()
router = APIRouter()

@router.post("/command")
async def admin_command(payload: dict, db: AsyncSession = Depends(get_db), _: bool = Depends(require_admin)):
    command = payload.get("command", "").lower()
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        if "revenue" in command or "earned" in command:
            repo = AnalyticsRepository(db)
            today = await repo.daily_revenue()
            by_niche = await repo.revenue_by_niche()
            progress = min(100, int(today / 180 * 100))
            bar = "#" * (progress // 10) + "-" * (10 - progress // 10)
            return {"response": f"Daily: ${today:.2f}/180 [{bar}] {progress}%. Niches: {by_niche}"}
        elif "add" in command and "discovery" in command:
            city = payload.get("city", "Miami")
            for cat in settings.SERVICE_CATEGORIES:
                await r.rpush("queue:discovery", json.dumps({"action": "discover", "city": city, "categories": [cat]}))
            return {"response": f"Discovery launched for {city}"}
        elif "sales" in command or "sequence" in command:
            await r.rpush("queue:sales", json.dumps({"action": "run_sequences"}))
            return {"response": "Sales sequences triggered"}
        elif "niche" in command:
            await r.rpush("queue:niche", json.dumps({"action": "discover_niches"}))
            return {"response": "NicheAgent activated"}
        elif "campaign" in command:
            niche = payload.get("niche", "service")
            await r.rpush("queue:campaign", json.dumps({"action": "launch_campaign", "niche": niche, "cities": settings.DISCOVERY_CITIES[:3]}))
            return {"response": f"Campaign launched: {niche}"}
        elif "queue" in command:
            queues = ["queue:discovery","queue:outreach","queue:qualify","queue:routing","queue:billing","queue:analytics","queue:sales","queue:niche","queue:landing","queue:campaign"]
            depths = {}
            for q in queues:
                depths[q] = await r.llen(q)
            return {"response": str(depths), "data": depths}
        else:
            return {"response": "Commands: revenue | add <city> to discovery | run sales | find new niches | launch campaigns for <niche> | check queue depths"}
    finally:
        await r.close()

@router.get("/stats")
async def admin_stats(db: AsyncSession = Depends(get_db), _: bool = Depends(require_admin)):
    repo = AnalyticsRepository(db)
    return {"daily_revenue": await repo.daily_revenue(), "by_niche": await repo.revenue_by_niche(), "conversion_rate": await repo.lead_conversion_rate()}


@router.get("/agents-health")
async def agents_health(db: AsyncSession = Depends(get_db), _: bool = Depends(require_admin)):
    queues = ["queue:discovery","queue:outreach","queue:qualify","queue:routing","queue:billing","queue:analytics","queue:sales","queue:niche","queue:landing","queue:campaign"]
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        queue_depths = {}
        for q in queues:
            queue_depths[q] = await r.llen(q)
    finally:
        await r.close()

    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    rows = await db.execute(
        select(
            AgentLog.agent_name,
            func.count().label("events"),
            func.sum(case((AgentLog.status == "error", 1), else_=0)).label("errors"),
            func.max(AgentLog.created_at).label("last_seen"),
        )
        .where(AgentLog.created_at >= since)
        .group_by(AgentLog.agent_name)
    )

    by_agent = {}
    for agent_name, events, errors, last_seen in rows.all():
        by_agent[agent_name] = {
            "events_last_30m": int(events or 0),
            "errors_last_30m": int(errors or 0),
            "last_seen": last_seen.isoformat() if last_seen else None,
            "healthy": bool(events) and int(errors or 0) == 0,
        }

    return {
        "window_minutes": 30,
        "queue_depths": queue_depths,
        "agents": by_agent,
    }
