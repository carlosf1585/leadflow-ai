import uuid
from datetime import datetime, date
from typing import Dict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import RevenueEvent, Lead, LeadStatus


class AnalyticsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record_revenue(self, data: dict):
        data.setdefault("id", str(uuid.uuid4()))
        event = RevenueEvent(**data)
        self.db.add(event)
        await self.db.flush()
        return event

    async def daily_revenue(self, target_date: date = None) -> float:
        target_date = target_date or date.today()
        start = datetime.combine(target_date, datetime.min.time())
        end = datetime.combine(target_date, datetime.max.time())
        result = await self.db.execute(
            select(func.sum(RevenueEvent.amount)).where(RevenueEvent.created_at.between(start, end))
        )
        return float(result.scalar() or 0.0)

    async def revenue_by_niche(self) -> Dict[str, float]:
        result = await self.db.execute(
            select(RevenueEvent.niche, func.sum(RevenueEvent.amount)).group_by(RevenueEvent.niche)
        )
        return {row[0]: float(row[1]) for row in result.all() if row[0]}

    async def lead_conversion_rate(self) -> float:
        total = (await self.db.execute(select(func.count(Lead.id)))).scalar() or 0
        charged = (await self.db.execute(select(func.count(Lead.id)).where(Lead.status == LeadStatus.CHARGED))).scalar() or 0
        return round(charged / total * 100, 2) if total > 0 else 0.0
