import uuid, stripe, structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import get_current_business
from app.db.database import get_db
from app.db.models import Subscription
from app.db.repositories.business_repo import BusinessRepository
stripe.api_key = settings.STRIPE_SECRET_KEY
log = structlog.get_logger()
router = APIRouter()

@router.post("/setup-intent")
async def create_setup_intent(db: AsyncSession = Depends(get_db), business_id: str = Depends(get_current_business)):
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Not found")
    if not business.stripe_customer_id:
        customer = stripe.Customer.create(email=business.email, name=business.name)
        business.stripe_customer_id = customer["id"]
        await db.commit()
    intent = stripe.SetupIntent.create(customer=business.stripe_customer_id)
    return {"client_secret": intent["client_secret"]}

@router.post("/subscribe")
async def subscribe(db: AsyncSession = Depends(get_db), business_id: str = Depends(get_current_business)):
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business or not business.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Set up payment first")
    sub = stripe.Subscription.create(
        customer=business.stripe_customer_id,
        items=[{"price_data": {"currency": "usd", "product_data": {"name": "LeadFlow Basic"}, "unit_amount": 29900, "recurring": {"interval": "month"}}}],
        payment_behavior="default_incomplete",
    )
    db_sub = Subscription(id=str(uuid.uuid4()), business_id=business_id, stripe_subscription_id=sub["id"])
    db.add(db_sub)
    await db.commit()
    return {"subscription_id": sub["id"], "status": sub["status"]}