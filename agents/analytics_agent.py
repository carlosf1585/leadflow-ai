import asyncio
import structlog
from agents.base_agent import BaseAgent
from app.db.database import AsyncSessionLocal
from app.db.repositories.analytics_repo import AnalyticsRepository

log = structlog.get_logger()
QUEUE_ANALYTICS = "queue:analytics"


class AnalyticsAgent(BaseAgent):
    name = "analytics_agent"
    queue = QUEUE_ANALYTICS

    async def process(self, payload: dict):
        action = payload.get("action")
        if action == "record_revenue":
            async with AsyncSessionLocal() as db:
                repo = AnalyticsRepository(db)
                await repo.record_revenue({
                    "business_id": payload.get("business_id"),
                    "lead_id": payload.get("lead_id"),
                    "amount": float(payload.get("amount", 0)),
                    "event_type": payload.get("event_type", "lead_charge"),
                    "niche": payload.get("niche"),
                    "city": payload.get("city"),
                    "stripe_payment_intent_id": payload.get("stripe_payment_intent_id"),
                })
                await db.commit()
                log.info("Revenue recorded", amount=payload.get("amount"))
        elif action == "daily_report":
            async with AsyncSessionLocal() as db:
                repo = AnalyticsRepository(db)
                revenue = await repo.daily_revenue()
                by_niche = await repo.revenue_by_niche()
                log.info("Daily report", revenue=revenue, by_niche=by_niche)


if __name__ == "__main__":
    asyncio.run(AnalyticsAgent().run())
