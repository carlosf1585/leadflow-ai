import uuid
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import create_access_token, hash_password, verify_password, get_current_business
from app.db.database import get_db
from app.db.models import ServiceType, BusinessStatus
from app.db.repositories.business_repo import BusinessRepository

log = structlog.get_logger()
router = APIRouter()


class BusinessRegister(BaseModel):
    name: str
    email: str
    password: str
    phone: str = None
    address: str = None
    city: str
    state: str = None
    service_type: ServiceType
    latitude: float = None
    longitude: float = None


class BusinessLogin(BaseModel):
    email: str
    password: str


@router.post("/register")
async def register(data: BusinessRegister, db: AsyncSession = Depends(get_db)):
    repo = BusinessRepository(db)
    if await repo.get_by_email(data.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    business = await repo.create({
        "id": str(uuid.uuid4()),
        "name": data.name,
        "email": data.email,
        "hashed_password": hash_password(data.password),
        "phone": data.phone,
        "address": data.address,
        "city": data.city,
        "state": data.state,
        "service_type": data.service_type,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "status": BusinessStatus.PROSPECT,
    })
    token = create_access_token({"sub": business.id})
    return {"access_token": token, "token_type": "bearer", "business_id": business.id}


@router.post("/login")
async def login(data: BusinessLogin, db: AsyncSession = Depends(get_db)):
    repo = BusinessRepository(db)
    business = await repo.get_by_email(data.email)
    if not business or not verify_password(data.password, business.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": business.id})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), business_id: str = Depends(get_current_business)):
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Not found")
    return {"id": business.id, "name": business.name, "status": business.status, "service_type": business.service_type, "city": business.city}
