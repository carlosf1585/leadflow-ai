import asyncio
import os
import structlog
from openai import AsyncOpenAI
from agents.base_agent import BaseAgent
from app.core.config import settings

log = structlog.get_logger()
QUEUE_LANDING = "queue:landing"


class LandingAgent(BaseAgent):
    name = "landing_agent"
    queue = QUEUE_LANDING

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.output_dir = "/app/static/landing"
        os.makedirs(self.output_dir, exist_ok=True)

    async def process(self, payload: dict):
        niche = payload.get("niche", "service")
        city = payload.get("city", "your city")
        filename = f"{niche.replace(' ', '-')}-{city.replace(' ', '-').lower()}.html"
        filepath = os.path.join(self.output_dir, filename)
        if os.path.exists(filepath):
            return
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_SMART,
            max_tokens=3000,
            messages=[{"role": "user", "content": f"Create a complete HTML landing page for {niche} lead generation in {city}. Form POSTs to /api/leads/submit. Mobile responsive. Strong CTA. Return only HTML."}],
        )
        html = msg.choices[0].message.content.strip()
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        log.info("Landing page created", filename=filename)


if __name__ == "__main__":
    asyncio.run(LandingAgent().run())
