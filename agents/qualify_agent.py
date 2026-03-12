import asyncio
import json

import structlog
from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import LeadStatus
from app.db.repositories.lead_repo import LeadRepository

log = structlog.get_logger()
QUEUE_QUALIFY = "queue:qualify"
QUEUE_ROUTING = "queue:routing"


class QualifyAgent(BaseAgent):
    name = "qualify_agent"
    queue = QUEUE_QUALIFY

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def _qualify_lead(self, lead: dict) -> dict:
        prompt = f"""Analyze this service lead. Return JSON only.
Name: {lead.get('consumer_name')}
Phone: {lead.get('consumer_phone')}
Service: {lead.get('service_type')}
Description: {lead.get('description')}
City: {lead.get('city')}

Return: {{"score": 0-100, "spam": true/false, "urgency": true/false, "reason": "one sentence"}}"""
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_FAST,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return json.loads(msg.choices[0].message.content)

    async def process(self, payload: dict):
        lead_id = payload["lead_id"]
        async with AsyncSessionLocal() as db:
            repo = LeadRepository(db)
            lead = await repo.get_by_id(lead_id)
            if not lead:
                return
            try:
                result = await self._qualify_lead({
                    "consumer_name": lead.consumer_name,
                    "consumer_phone": lead.consumer_phone,
                    "service_type": lead.service_type.value,
                    "description": lead.description,
                    "city": lead.city,
                })
            except Exception as e:
                log.error("Qualify error", error=str(e))
                result = {"score": 50, "spam": False, "urgency": False}

            if result.get("spam"):
                await repo.update_status(lead_id, LeadStatus.SPAM, spam_flag=True)
                await db.commit()
                return

            score = float(result.get("score", 50))
            urgency = bool(result.get("urgency", False))
            await repo.update_status(lead_id, LeadStatus.QUALIFIED, ai_score=score, urgency=urgency)
            await db.commit()
            if score >= 40:
                await self.publish(QUEUE_ROUTING, {"action": "route_lead", "lead_id": lead_id, "score": score, "urgency": urgency})
            log.info("Lead qualified", lead_id=lead_id, score=score)


if __name__ == "__main__":
    asyncio.run(QualifyAgent().run())
