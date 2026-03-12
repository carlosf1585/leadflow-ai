import uuid
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Lead, LeadAssignment, LeadStatus


class LeadRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Lead:
        data.setdefault("id", str(uuid.uuid4()))
        lead = Lead(**data)
        self.db.add(lead)
        await self.db.flush()
        return lead

    async def get_by_id(self, lead_id: str) -> Optional[Lead]:
        result = await self.db.execute(select(Lead).where(Lead.id == lead_id))
        return result.scalar_one_or_none()

    async def update_status(self, lead_id: str, status: LeadStatus, **kwargs):
        lead = await self.get_by_id(lead_id)
        if lead:
            lead.status = status
            for k, v in kwargs.items():
                setattr(lead, k, v)
            await self.db.flush()
        return lead


class AssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> LeadAssignment:
        data.setdefault("id", str(uuid.uuid4()))
        a = LeadAssignment(**data)
        self.db.add(a)
        await self.db.flush()
        return a

    async def mark_charged(self, assignment_id: str, payment_intent_id: str):
        a = await self.db.get(LeadAssignment, assignment_id)
        if a:
            a.charged = True
            a.stripe_payment_intent_id = payment_intent_id
            await self.db.flush()
