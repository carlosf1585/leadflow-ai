import json
import uuid
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import get_current_business
from app.db.database import get_db
from app.db.models import ServiceType
from app.db.repositories.lead_repo import LeadRepository

log = structlog.get_logger()
router = APIRouter()
QUEUE_QUALIFY = "queue:qualify"


class LeadSubmit(BaseModel):
    consumer_name: str
    consumer_phone: str
    consumer_email: str = None
    service_type: ServiceType
    description: str = None
    city: str
    state: str = None
    zip_code: str = None
    latitude: float = None
    longitude: float = None


@router.post("/submit")
async def submit_lead(data: LeadSubmit, db: AsyncSession = Depends(get_db)):
    repo = LeadRepository(db)
    lead = await repo.create({
        "id": str(uuid.uuid4()),
        "consumer_name": data.consumer_name,
        "consumer_phone": data.consumer_phone,
        "consumer_email": data.consumer_email,
        "service_type": data.service_type,
        "description": data.description,
        "city": data.city,
        "state": data.state,
        "zip_code": data.zip_code,
        "latitude": data.latitude,
        "longitude": data.longitude,
    })
    r = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await r.rpush(QUEUE_QUALIFY, json.dumps({"action": "qualify", "lead_id": lead.id}))
    await r.close()
    log.info("Lead submitted", lead_id=lead.id)
    return {"lead_id": lead.id, "status": "queued"}


@router.get("/my-leads")
async def get_my_leads(db: AsyncSession = Depends(get_db), business_id: str = Depends(get_current_business)):
    from sqlalchemy import select
    from app.db.models import LeadAssignment, Lead
    result = await db.execute(select(Lead).join(LeadAssignment).where(LeadAssignment.business_id == business_id))
    leads = result.scalars().all()
    return [{"id": l.id, "consumer_name": l.consumer_name, "service_type": l.service_type, "city": l.city, "status": l.status, "created_at": str(l.created_at)} for l in leads]
