import stripe, structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Business, BusinessStatus, Subscription, SubscriptionStatus
stripe.api_key = settings.STRIPE_SECRET_KEY
log = structlog.get_logger()
router = APIRouter()

@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    etype = event["type"]
    data = event["data"]["object"]
    if etype == "customer.subscription.updated":
        result = await db.execute(select(Subscription).where(Subscription.stripe_subscription_id == data["id"]))
        sub = result.scalar_one_or_none()
        if sub:
            sub.status = SubscriptionStatus.ACTIVE if data["status"] == "active" else SubscriptionStatus.PAST_DUE
            await db.commit()
    elif etype == "payment_method.attached":
        result = await db.execute(select(Business).where(Business.stripe_customer_id == data["customer"]))
        biz = result.scalar_one_or_none()
        if biz:
            biz.stripe_payment_method_id = data["id"]
            biz.status = BusinessStatus.ACTIVE
            await db.commit()
            log.info("Business activated", name=biz.name)
    log.info("Webhook", event_type=etype)
    return {"received": True}