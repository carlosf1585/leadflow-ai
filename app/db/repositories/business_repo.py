import math
import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Business, BusinessStatus, ServiceType


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


class BusinessRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> Business:
        data.setdefault("id", str(uuid.uuid4()))
        b = Business(**data)
        self.db.add(b)
        await self.db.flush()
        return b

    async def get_by_id(self, business_id: str) -> Optional[Business]:
        result = await self.db.execute(select(Business).where(Business.id == business_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[Business]:
        result = await self.db.execute(select(Business).where(Business.email == email))
        return result.scalar_one_or_none()

    async def get_by_place_id(self, place_id: str) -> Optional[Business]:
        result = await self.db.execute(select(Business).where(Business.google_place_id == place_id))
        return result.scalar_one_or_none()

    async def upsert_from_discovery(self, data: dict) -> Business:
        existing = await self.get_by_place_id(data.get("google_place_id", ""))
        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
            await self.db.flush()
            return existing
        return await self.create(data)

    async def find_nearby_active(self, lat, lon, service_type, radius_km=50.0, limit=3):
        result = await self.db.execute(
            select(Business).where(
                Business.status == BusinessStatus.ACTIVE,
                Business.service_type == service_type,
                Business.stripe_payment_method_id.isnot(None),
            )
        )
        businesses = result.scalars().all()
        nearby = []
        for b in businesses:
            if b.latitude and b.longitude:
                dist = haversine_km(lat, lon, b.latitude, b.longitude)
                if dist <= radius_km:
                    nearby.append((dist, b))
        nearby.sort(key=lambda x: x[0])
        return nearby[:limit]

    async def update_status(self, business_id: str, status: BusinessStatus):
        await self.db.execute(update(Business).where(Business.id == business_id).values(status=status))
