import asyncio
import json
import structlog
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.repositories.analytics_repo import AnalyticsRepository

log = structlog.get_logger()
QUEUE_CAMPAIGN = "queue:campaign"


class CampaignAgent(BaseAgent):
    name = "campaign_agent"
    queue = QUEUE_CAMPAIGN

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def process(self, payload: dict):
        action = payload.get("action")
        if action == "launch_campaign":
            niche = payload.get("niche")
            cities = payload.get("cities", settings.DISCOVERY_CITIES[:3])
            for city in cities:
                msg = await self.openai.chat.completions.create(
                    model=settings.OPENAI_MODEL_FAST,
                    max_tokens=200,
                    messages=[{"role": "user", "content": f"Google Ads copy for {niche} in {city}. Return JSON: {{headline1, headline2, description, keywords}}"}],
                    response_format={"type": "json_object"},
                )
                ad_copy = json.loads(msg.choices[0].message.content)
                log.info("Ad copy generated", niche=niche, city=city, copy=ad_copy)
        elif action == "check_performance":
            async with AsyncSessionLocal() as db:
                repo = AnalyticsRepository(db)
                revenue = await repo.daily_revenue()
                by_niche = await repo.revenue_by_niche()
                log.info("Campaign performance", daily_revenue=revenue, by_niche=by_niche)


if __name__ == "__main__":
    asyncio.run(CampaignAgent().run())
