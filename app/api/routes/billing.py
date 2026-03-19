import uuid

import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_business
from app.db.database import get_db
from app.db.models import Subscription, SubscriptionStatus
from app.db.repositories.business_repo import BusinessRepository

stripe.api_key = settings.STRIPE_SECRET_KEY
log = structlog.get_logger()
router = APIRouter()

PLANS = {
    "pay_per_lead": {
        "name": "Pay Per Lead",
        "description": "No subscription. Pay only for leads you receive. Premium pricing.",
        "price_month": 0,
        "monthly_leads": 999,
        "lead_price_multiplier": 1.0,
        "stripe_price_id": None,
        "features": [
            "No monthly commitment",
            "Pay only per lead received",
            "Premium pricing per lead",
            "Exclusive leads to your area",
            "Cancel anytime",
        ],
    },
    "starter": {
        "name": "Starter",
        "description": "Perfect for growing businesses. Up to 10 leads per month.",
        "price_month": settings.PLAN_STARTER_PRICE_MONTH,
        "monthly_leads": settings.PLAN_STARTER_MONTHLY_LEADS,
        "lead_price_multiplier": 0.78,
        "stripe_price_id": settings.STRIPE_PRICE_STARTER,
        "features": [
            f"Up to {settings.PLAN_STARTER_MONTHLY_LEADS} leads/month",
            "~22% discount vs Pay Per Lead",
            "Exclusive leads to your area",
            "Email delivery in real-time",
            "Monthly analytics report",
        ],
    },
    "growth": {
        "name": "Growth",
        "description": "For established businesses scaling fast. Up to 25 leads per month.",
        "price_month": settings.PLAN_GROWTH_PRICE_MONTH,
        "monthly_leads": settings.PLAN_GROWTH_MONTHLY_LEADS,
        "lead_price_multiplier": 0.62,
        "stripe_price_id": settings.STRIPE_PRICE_GROWTH,
        "features": [
            f"Up to {settings.PLAN_GROWTH_MONTHLY_LEADS} leads/month",
            "~38% discount vs Pay Per Lead",
            "Priority lead routing",
            "Dedicated account support",
            "Advanced analytics dashboard",
        ],
    },
}


class SetupIntentRequest(BaseModel):
    plan: str = "pay_per_lead"


class SubscribeRequest(BaseModel):
    plan: str


@router.get("/plans")
async def get_plans():
    result = {}
    for plan_id, plan in PLANS.items():
        result[plan_id] = {
            "id": plan_id,
            "name": plan["name"],
            "description": plan["description"],
            "price_month": plan["price_month"],
            "monthly_leads": plan["monthly_leads"],
            "features": plan["features"],
        }
    return result


@router.post("/setup-intent")
async def create_setup_intent(
    data: SetupIntentRequest,
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Not found")

    if not getattr(business, "email_verified", False):
        raise HTTPException(status_code=403, detail="Verify your email before setting up billing.")

    if data.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Invalid plan")

    if not business.stripe_customer_id:
        customer = stripe.Customer.create(
            email=business.email,
            name=business.name,
            metadata={"business_id": business_id, "plan": data.plan},
        )
        business.stripe_customer_id = customer["id"]

    business.plan = data.plan
    await db.flush()

    intent = stripe.SetupIntent.create(
        customer=business.stripe_customer_id,
        payment_method_types=["card"],
        metadata={"plan": data.plan},
    )
    return {
        "client_secret": intent["client_secret"],
        "customer_id": business.stripe_customer_id,
        "plan": data.plan,
        "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
    }


@router.post("/subscribe")
async def subscribe(
    data: SubscribeRequest,
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    if data.plan not in ("starter", "growth"):
        raise HTTPException(status_code=400, detail="Use 'starter' or 'growth' plan for subscription")

    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business or not business.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Set up payment first via /billing/setup-intent")
    if not business.stripe_payment_method_id:
        raise HTTPException(status_code=400, detail="Card not yet saved. Complete card setup first.")

    plan_cfg = PLANS[data.plan]
    price_id = plan_cfg["stripe_price_id"]
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Stripe Price ID not configured for plan '{data.plan}'")

    result = await db.execute(
        select(Subscription).where(
            Subscription.business_id == business_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        stripe.Subscription.cancel(existing.stripe_subscription_id)
        existing.status = SubscriptionStatus.CANCELLED
        await db.flush()

    sub = stripe.Subscription.create(
        customer=business.stripe_customer_id,
        items=[{"price": price_id}],
        default_payment_method=business.stripe_payment_method_id,
        metadata={"business_id": business_id, "plan": data.plan},
    )

    db_sub = Subscription(
        id=str(uuid.uuid4()),
        business_id=business_id,
        stripe_subscription_id=sub["id"],
        status=SubscriptionStatus.ACTIVE,
        plan=data.plan,
        monthly_lead_limit=plan_cfg["monthly_leads"],
        price_per_month=plan_cfg["price_month"],
    )
    db.add(db_sub)
    business.plan = data.plan
    await db.flush()

    log.info("Subscribed", business_id=business_id, plan=data.plan, sub_id=sub["id"])
    return {
        "subscription_id": sub["id"],
        "status": sub["status"],
        "plan": data.plan,
        "monthly_leads": plan_cfg["monthly_leads"],
        "price_month": plan_cfg["price_month"],
    }


@router.delete("/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    result = await db.execute(
        select(Subscription).where(
            Subscription.business_id == business_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    stripe.Subscription.cancel(sub.stripe_subscription_id)
    sub.status = SubscriptionStatus.CANCELLED

    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if business:
        business.plan = "pay_per_lead"
    await db.flush()
    return {"message": "Subscription cancelled. Reverted to Pay Per Lead."}
