import asyncio
import uuid
import secrets
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import create_access_token, get_current_business, hash_password, verify_password
from app.db.database import get_db
from app.db.models import Business, BusinessStatus, Lead, LeadAssignment, ServiceType, Subscription

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
    plan: str = "pay_per_lead"
    latitude: float = None
    longitude: float = None


class BusinessLogin(BaseModel):
    email: str
    password: str


PLAN_LABELS = {
    "pay_per_lead": "Pay Per Lead",
    "starter": "Starter - $149/mo",
    "growth": "Growth - $299/mo",
}

PLAN_NEXT_STEPS = {
    "pay_per_lead": "You are on the Pay Per Lead plan.",
    "starter": "You selected the Starter Plan ($149/mo).",
    "growth": "You selected the Growth Plan ($299/mo).",
}


def _send_email_resend(to_email: str, subject: str, html: str):
    try:
        api_key = getattr(settings, "RESEND_API_KEY", None)
        if not api_key:
            log.error("resend_api_key_missing")
            return
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "from": f"LeadFlow360 <{settings.SMTP_FROM}>",
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
            timeout=15,
        )
        if resp.status_code in (200, 201):
            log.info("email_sent_resend", to=to_email, subject=subject)
        else:
            log.error("resend_send_failed", status=resp.status_code, body=resp.text, to=to_email)
    except Exception as e:
        log.error("resend_exception", error=str(e), to=to_email)


def _send_verification_email(to_email: str, business_name: str, token: str):
    verify_url = f"https://leadflow360.ca/?verify={token}"
    html = f"<html><body><h1>Verify your email, {business_name}</h1><a href=\"{verify_url}\">Verify My Email</a></body></html>"
    _send_email_resend(to_email, "LeadFlow360 - Please verify your email address", html)


def _send_welcome_email(to_email: str, business_name: str, service_type: str, city: str, plan: str = "pay_per_lead"):
    plan_label = PLAN_LABELS.get(plan, plan.replace("_", " ").title())
    html = f"<html><body><h1>Welcome, {business_name}!</h1><p>Your account is live. Plan: {plan_label}</p></body></html>"
    _send_email_resend(to_email, "Welcome to LeadFlow360 - Your leads are on the way!", html)


@router.post("/register")
async def register(data: BusinessRegister, db: AsyncSession = Depends(get_db)):
    repo_result = await db.execute(select(Business).where(Business.email == data.email))
    if repo_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    if data.plan not in ("pay_per_lead", "starter", "growth"):
        raise HTTPException(status_code=400, detail="Invalid plan.")
    verification_token = secrets.token_urlsafe(32)
    business = Business(
        id=str(uuid.uuid4()),
        name=data.name,
        email=data.email,
        hashed_password=hash_password(data.password),
        phone=data.phone,
        address=data.address,
        city=data.city,
        state=data.state,
        service_type=data.service_type,
        plan=data.plan,
        latitude=data.latitude,
        longitude=data.longitude,
        status=BusinessStatus.PROSPECT,
        email_verified=False,
        email_verification_token=verification_token,
    )
    db.add(business)
    await db.commit()
    await db.refresh(business)
    token = create_access_token({"sub": business.id})
    asyncio.ensure_future(
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _send_verification_email(
                to_email=data.email,
                business_name=data.name,
                token=verification_token,
            )
        )
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": business.id,
        "plan": data.plan,
        "needs_card_setup": True,
        "email_verification_sent": True,
    }


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Business).where(Business.email_verification_token == token)
    )
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    business.email_verified = True
    business.email_verification_token = None
    await db.commit()
    return RedirectResponse(url="https://leadflow360.ca/?verification=success")


@router.post("/login")
async def login(data: BusinessLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Business).where(Business.email == data.email))
    business = result.scalar_one_or_none()
    if not business or not verify_password(data.password, business.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": business.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": business.id,
        "plan": getattr(business, "plan", "pay_per_lead"),
    }


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    result = await db.execute(select(Business).where(Business.id == business_id))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Not found")
    rows_result = await db.execute(
        select(Lead, LeadAssignment)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .where(LeadAssignment.business_id == business_id)
        .order_by(Lead.created_at.desc())
        .limit(50)
    )
    rows = rows_result.all()
    leads_data = [
        {
            "id": lead.id,
            "consumer_name": lead.consumer_name,
            "consumer_phone": lead.consumer_phone,
            "consumer_email": lead.consumer_email,
            "service_type": lead.service_type.value if lead.service_type else None,
            "description": lead.description,
            "city": lead.city,
            "status": lead.status.value if lead.status else None,
            "ai_score": lead.ai_score,
            "urgency": lead.urgency,
            "price": assignment.price,
            "charged": assignment.charged,
            "received_at": str(lead.created_at),
        }
        for lead, assignment in rows
    ]
    sub_result = await db.execute(
        select(Subscription).where(
            Subscription.business_id == business_id,
            Subscription.status == "active",
        )
    )
    subscription = sub_result.scalar_one_or_none()
    return {
        "id": business.id,
        "name": business.name,
        "email": business.email,
        "phone": business.phone,
        "service_type": business.service_type.value if business.service_type else None,
        "city": business.city,
        "status": business.status.value if business.status else None,
        "plan": getattr(business, "plan", "pay_per_lead"),
        "has_payment_method": bool(business.stripe_payment_method_id),
        "email_verified": getattr(business, "email_verified", False),
        "subscription": {
            "plan": subscription.plan if subscription else None,
            "monthly_lead_limit": subscription.monthly_lead_limit if subscription else None,
            "leads_used": subscription.leads_used_this_month if subscription else None,
            "status": subscription.status.value if subscription else None,
        } if subscription else None,
        "leads": leads_data,
        "total_leads": len(leads_data),
        "total_charged": sum(a.price for _, a in rows if a.charged),
    }
