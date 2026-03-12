import asyncio, json
import redis.asyncio as aioredis
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
log = structlog.get_logger()

async def _push(queue, payload):
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await r.rpush(queue, json.dumps(payload))
    finally:
        await r.close()

async def trigger_discovery():
    for city in settings.DISCOVERY_CITIES:
        await _push("queue:discovery", {"action": "discover", "city": city, "categories": settings.SERVICE_CATEGORIES})
    log.info("Discovery cron triggered")

async def trigger_daily_report():
    await _push("queue:analytics", {"action": "daily_report"})

async def trigger_niche_discovery():
    await _push("queue:niche", {"action": "discover_niches"})

async def trigger_sales_sequences():
    await _push("queue:sales", {"action": "run_sequences"})

async def trigger_campaign_check():
    await _push("queue:campaign", {"action": "check_performance"})

def create_scheduler():
    s = AsyncIOScheduler()
    s.add_job(trigger_discovery, "cron", hour=2, minute=0)
    s.add_job(trigger_daily_report, "cron", hour=8, minute=0)
    s.add_job(trigger_niche_discovery, "cron", day_of_week="mon", hour=3, minute=0)
    s.add_job(trigger_sales_sequences, "cron", hour=6, minute=0)
    s.add_job(trigger_campaign_check, "cron", hour=10, minute=0)
    return s

if __name__ == "__main__":
    async def main():
        scheduler = create_scheduler()
        scheduler.start()
        log.info("Scheduler started")
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown()
    asyncio.run(main())