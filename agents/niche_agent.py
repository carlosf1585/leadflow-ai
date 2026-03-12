import asyncio
import json
import structlog
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.repositories.analytics_repo import AnalyticsRepository

log = structlog.get_logger()
QUEUE_NICHE = "queue:niche"
QUEUE_DISCOVERY = "queue:discovery"
QUEUE_CAMPAIGN = "queue:campaign"
QUEUE_LANDING = "queue:landing"


class NicheAgent(BaseAgent):
    name = "niche_agent"
    queue = QUEUE_NICHE

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def process(self, payload: dict):
        async with AsyncSessionLocal() as db:
            repo = AnalyticsRepository(db)
            current_niches = await repo.revenue_by_niche()
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_SMART,
            max_tokens=600,
            messages=[{"role": "user", "content": f"Suggest 3 NEW profitable local service niches for lead gen. Current: {json.dumps(current_niches)}. Return JSON array: [{{\"niche\": \"..\", \"estimated_lead_price\": 0, \"reason\": \"...\"}}]"}],
            response_format={"type": "json_object"},
        )
        try:
            data = json.loads(msg.choices[0].message.content)
            suggestions = data if isinstance(data, list) else data.get("niches", [])
        except Exception:
            return
        for s in suggestions:
            niche = s.get("niche")
            for city in settings.DISCOVERY_CITIES[:3]:
                await self.publish(QUEUE_DISCOVERY, {"action": "discover", "city": city, "categories": [niche]})
                await self.publish(QUEUE_LANDING, {"action": "create_landing", "niche": niche, "city": city})
            await self.publish(QUEUE_CAMPAIGN, {"action": "launch_campaign", "niche": niche, "cities": settings.DISCOVERY_CITIES[:3]})
            log.info("New niche queued", niche=niche)


if __name__ == "__main__":
    asyncio.run(NicheAgent().run())
