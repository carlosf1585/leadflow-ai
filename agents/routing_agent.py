import asyncio
import structlog
from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import LeadStatus
from app.db.repositories.business_repo import BusinessRepository
from app.db.repositories.lead_repo import AssignmentRepository, LeadRepository

log = structlog.get_logger()
QUEUE_ROUTING = "queue:routing"
QUEUE_BILLING = "queue:billing"

PRICE_MAP = {
    "plumbing": settings.LEAD_PRICE_PLUMBING,
    "roofing": settings.LEAD_PRICE_ROOFING,
    "hvac": settings.LEAD_PRICE_HVAC,
    "pest_control": settings.LEAD_PRICE_PEST_CONTROL,
    "dental": settings.LEAD_PRICE_DENTAL,
    "auto_accident": settings.LEAD_PRICE_AUTO_ACCIDENT,
}


class RoutingAgent(BaseAgent):
    name = "routing_agent"
    queue = QUEUE_ROUTING

    async def process(self, payload: dict):
        lead_id = payload["lead_id"]
        urgency = payload.get("urgency", False)
        async with AsyncSessionLocal() as db:
            lead_repo = LeadRepository(db)
            biz_repo = BusinessRepository(db)
            assign_repo = AssignmentRepository(db)
            lead = await lead_repo.get_by_id(lead_id)
            if not lead or not lead.latitude or not lead.longitude:
                log.error("Lead not found or missing coords", lead_id=lead_id)
                return
            nearby = await biz_repo.find_nearby_active(lead.latitude, lead.longitude, lead.service_type.value)
            if not nearby:
                log.warning("No nearby businesses", lead_id=lead_id)
                return
            base_price = PRICE_MAP.get(lead.service_type.value, settings.LEAD_PRICE_DEFAULT)
            price = base_price * 1.5 if urgency else base_price
            assignment_ids = []
            for dist, business in nearby:
                assignment = await assign_repo.create({"lead_id": lead_id, "business_id": business.id, "price": price, "distance_km": dist})
                assignment_ids.append(assignment.id)
            await lead_repo.update_status(lead_id, LeadStatus.ROUTED, price=price)
            await db.commit()
            for aid in assignment_ids:
                await self.publish(QUEUE_BILLING, {"action": "charge", "assignment_id": aid, "lead_id": lead_id, "price": price})
            log.info("Lead routed", lead_id=lead_id, businesses=len(nearby), price=price)


if __name__ == "__main__":
    asyncio.run(RoutingAgent().run())
