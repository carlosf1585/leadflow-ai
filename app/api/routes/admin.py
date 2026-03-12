import json
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import require_admin
from app.db.database import get_db
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