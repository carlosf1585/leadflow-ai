import asyncio
import uuid
import smtplib
import secrets
import structlog
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, get_current_business, hash_password, verify_password
from app.db.database import get_db
from app.db.models import Business, BusinessStatus, Lead, LeadAssignment, ServiceType, Subscription, SubscriptionStatus
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
    plan: str = "pay_per_lead"
    latitude: float = None
    longitude: float = None


class BusinessLogin(BaseModel):
    email: str
    password: str


PLAN_LABELS = {
    "pay_per_lead": "Pay Per Lead",
    "starter": "Starter — $149/mo",
    "growth": "Growth — $299/mo",
}

PLAN_NEXT_STEPS = {
    "pay_per_lead": "You are on the <strong>Pay Per Lead</strong> plan. No monthly fee — you only pay when we deliver a lead. Your card will be saved for automatic billing after email verification.",
    "starter": "You selected the <strong>Starter Plan ($149/mo)</strong>. Up to 10 exclusive leads per month at a discounted rate. Verify your email first, then complete payment setup.",
    "growth": "You selected the <strong>Growth Plan ($299/mo)</strong>. Up to 25 exclusive leads per month at our best rate. Verify your email first, then complete payment setup.",
}


def _send_welcome_email(to_email: str, business_name: str, service_type: str, city: str, plan: str = "pay_per_lead"):
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'Welcome to LeadFlow360 — Your leads are on the way!'
        msg['From'] = f'LeadFlow360 <{settings.SMTP_FROM}>'
        msg['To'] = to_email
        plan_label = PLAN_LABELS.get(plan, plan.replace("_", " ").title())
        plan_note = PLAN_NEXT_STEPS.get(plan, "")
        html = f"""
<html><body style="font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0;">
<div style="max-width:600px;margin:0 auto;padding:40px 20px;">
  <div style="text-align:center;margin-bottom:30px;">
    <h1 style="color:#00d4ff;font-size:28px;margin:0;">LeadFlow<span style="color:#fff;">360</span></h1>
    <p style="color:#8b949e;margin:5px 0;">AI-Powered Lead Generation</p>
  </div>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:30px;">
    <h2 style="color:#fff;margin-top:0;">Welcome, {business_name}!</h2>
    <p style="color:#c9d1d9;line-height:1.6;">
      Your LeadFlow360 account is live. Our AI agents are now scanning for exclusive
      <strong style="color:#00d4ff;">{service_type}</strong> leads in
      <strong style="color:#00d4ff;">{city}</strong>.
    </p>
    <div style="background:#0d1117;border-radius:8px;padding:16px;margin:20px 0;">
      <p style="color:#00d4ff;margin:0 0 8px;font-weight:bold;">Your Plan: {plan_label}</p>
      <p style="color:#c9d1d9;margin:0;">{plan_note}</p>
    </div>
    <div style="background:#0d1117;border-radius:8px;padding:20px;margin:20px 0;">
      <h3 style="color:#00d4ff;margin-top:0;">What happens next:</h3>
      <ul style="color:#c9d1d9;line-height:1.8;padding-left:20px;">
        <li>Verify your email address to activate billing</li>
        <li>Complete your card setup in your dashboard</li>
        <li>Our AI scans thousands of sources for active buyers</li>
        <li>Leads are qualified and verified before delivery</li>
        <li>You receive <strong>exclusive leads</strong> — no sharing with competitors</li>
      </ul>
    </div>
  </div>
</div>
</body></html>
"""
        msg.attach(MIMEText(html, 'html'))
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, 587) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASS or settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())
        log.info("welcome_email_sent", to=to_email)
    except Exception as e:
        log.error("welcome_email_failed", error=str(e))


def _send_verification_email(to_email: str, business_name: str, token: str):
    try:
        verify_url = f"https://leadflow-ai-production-813c.up.railway.app/api/businesses/verify-email/{token}"
        msg = MIMEMultipart('alternative')
        msg['Subject'] = 'LeadFlow360 — Please verify your email address'
        msg['From'] = f'LeadFlow360 <{settings.SMTP_FROM}>'
        msg['To'] = to_email
        html = f"""
<html><body style="font-family:Arial,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:0;">
<div style="max-width:600px;margin:0 auto;padding:40px 20px;">
  <div style="text-align:center;margin-bottom:30px;">
    <h1 style="color:#00d4ff;font-size:28px;margin:0;">LeadFlow<span style="color:#fff;">360</span></h1>
  </div>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:12px;padding:30px;">
    <h2 style="color:#fff;margin-top:0;">Verify your email, {business_name}</h2>
    <p style="color:#c9d1d9;line-height:1.6;">
      Thanks for signing up! Click the button below to verify your email address and unlock billing setup.
    </p>
    <div style="text-align:center;margin:30px 0;">
      <a href="{verify_url}" style="background:#00d4ff;color:#06101b;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block;font-size:16px;">
        Verify My Email
      </a>
    </div>
    <p style="color:#8b949e;font-size:12px;">
      If you did not create this account, ignore this email.
    </p>
  </div>
</div>
</body></html>
"""
        msg.attach(MIMEText(html, 'html'))
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.SMTP_HOST, 587) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASS or settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())
        log.info("verification_email_sent", to=to_email)
    except Exception as e:
        log.error("verification_email_failed", error=str(e))


@router.post("/register")
async def register(data: BusinessRegister, db: AsyncSession = Depends(get_db)):
    repo = BusinessRepository(db)
    if await repo.get_by_email(data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    if data.plan not in ("pay_per_lead", "starter", "growth"):
        raise HTTPException(status_code=400, detail="Invalid plan. Choose: pay_per_lead, starter, growth")

    verification_token = secrets.token_urlsafe(32)

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
        "plan": data.plan,
        "latitude": data.latitude,
        "longitude": data.longitude,
        "status": BusinessStatus.PROSPECT,
        "email_verified": False,
        "email_verification_token": verification_token,
    })
    await db.flush()

    token = create_access_token({"sub": business.id})

    loop = asyncio.get_event_loop()
    asyncio.ensure_future(loop.run_in_executor(None, lambda: _send_verification_email(data.email, data.name, verification_token)))
    asyncio.ensure_future(loop.run_in_executor(None, lambda: _send_welcome_email(
        to_email=data.email,
        business_name=data.name,
        service_type=str(data.service_type.value if hasattr(data.service_type, 'value') else data.service_type),
        city=data.city,
        plan=data.plan,
    )))

    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": business.id,
        "plan": data.plan,
        "needs_card_setup": True,
        "email_verification_sent": True,
        "email_verified": False,
    }


@router.get("/verify-email/{token}")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Business).where(Business.email_verification_token == token))
    business = result.scalar_one_or_none()
    if not business:
        raise HTTPException(status_code=404, detail="Invalid or expired verification token")

    business.email_verified = True
    business.email_verification_token = None
    await db.flush()

    return RedirectResponse(url="https://leadflow360.ca/?verification=success")


@router.post("/login")
async def login(data: BusinessLogin, db: AsyncSession = Depends(get_db)):
    repo = BusinessRepository(db)
    business = await repo.get_by_email(data.email)
    if not business or not verify_password(data.password, business.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": business.id})
    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": business.id,
        "plan": getattr(business, "plan", "pay_per_lead"),
        "email_verified": bool(getattr(business, "email_verified", False)),
    }


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Not found")

    result = await db.execute(
        select(Lead, LeadAssignment)
        .join(LeadAssignment, Lead.id == LeadAssignment.lead_id)
        .where(LeadAssignment.business_id == business_id)
        .order_by(Lead.created_at.desc())
        .limit(50)
    )
    rows = result.all()
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
            Subscription.status == SubscriptionStatus.ACTIVE,
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
        "email_verified": bool(getattr(business, "email_verified", False)),
        "has_payment_method": bool(business.stripe_payment_method_id),
        "subscription": {
            "plan": subscription.plan if subscription else None,
            "monthly_lead_limit": subscription.monthly_lead_limit if subscription else None,
            "leads_used": subscription.leads_used_this_month if subscription else None,
            "status": subscription.status.value if subscription and subscription.status else None,
        } if subscription else None,
        "leads": leads_data,
        "total_leads": len(leads_data),
        "total_charged": sum(a.price for _, a in rows if a.charged),
    }
