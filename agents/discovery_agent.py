import asyncio
import uuid

import httpx
import structlog
from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import ServiceType
from app.db.repositories.business_repo import BusinessRepository

log = structlog.get_logger()

QUEUE_DISCOVERY = "queue:discovery"
QUEUE_OUTREACH = "queue:outreach"


class DiscoveryAgent(BaseAgent):
    name = "discovery_agent"
    queue = QUEUE_DISCOVERY

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def _fetch_places(self, query: str, city: str):
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": f"{query} in {city}", "key": settings.GOOGLE_MAPS_API_KEY}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def _score_business(self, business: dict) -> float:
        prompt = f"""Rate this local service business 0-100 for lead gen potential.
Name: {business.get('name')}
Rating: {business.get('rating', 'N/A')} ({business.get('user_ratings_total', 0)} reviews)
Return ONLY a number 0-100."""
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_FAST,
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return float(msg.choices[0].message.content.strip())
        except Exception:
            return 50.0

    async def process(self, payload: dict):
        city = payload.get("city", "New York")
        categories = payload.get("categories", settings.SERVICE_CATEGORIES)
        service_map = {
            "plumber": ServiceType.PLUMBING,
            "roofer": ServiceType.ROOFING,
            "hvac": ServiceType.HVAC,
            "pest control": ServiceType.PEST_CONTROL,
            "dentist": ServiceType.DENTAL,
        }
        async with AsyncSessionLocal() as db:
            repo = BusinessRepository(db)
            for category in categories:
                try:
                    places = await self._fetch_places(category, city)
                    for place in places[:20]:
                        score = await self._score_business(place)
                        location = place.get("geometry", {}).get("location", {})
                        data = {
                            "name": place.get("name", ""),
                            "email": f"contact@{place.get('name','biz').lower().replace(' ','').replace(',','')}example.com",
                            "address": place.get("formatted_address", ""),
                            "city": city,
                            "latitude": location.get("lat"),
                            "longitude": location.get("lng"),
                            "service_type": service_map.get(category, ServiceType.OTHER),
                            "google_place_id": place.get("place_id", str(uuid.uuid4())),
                            "rating": place.get("rating"),
                            "review_count": place.get("user_ratings_total", 0),
                            "ai_score": score,
                            "niche": category,
                        }
                        business = await repo.upsert_from_discovery(data)
                        if score >= 60:
                            await self.publish(QUEUE_OUTREACH, {
                                "action": "send_outreach",
                                "business_id": business.id,
                                "business_name": business.name,
                                "business_email": business.email,
                                "niche": category,
                                "city": city,
                            })
                    await db.commit()
                except Exception as e:
                    log.error("Discovery error", category=category, city=city, error=str(e))


if __name__ == "__main__":
    asyncio.run(DiscoveryAgent().run())
