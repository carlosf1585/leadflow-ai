import uuid
import smtplib
import structlog
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import create_access_token, hash_password, verify_password, get_current_business
from app.db.database import get_db
from app.db.models import ServiceType, BusinessStatus
from app.db.repositories.business_repo import BusinessRepository
from app.core.config import settings

log = structlog.get_logger()
router = APIRouter()


# ------------------------------------------------------------------ #
#  Schemas                                                             #
# ------------------------------------------------------------------ #

class BusinessRegister(BaseModel):
    name: str
    email: str
    password: str
    phone: str = None
    address: str = None
    city: str
    state: str = None
    service_type: ServiceType
    plan: str = "pay_per_lead"  # pay_per_lead | starter | growth
    latitude: float = None
    longitude: float = None


class BusinessLogin(BaseModel):
    email: str
    password: str


# ------------------------------------------------------------------ #
#  Welcome email                                                       #
# ------------------------------------------------------------------ #

PLAN_LABELS = {
    "pay_per_lead": "Pay Per Lead",
    "starter": "Starter — $149/mo",
    "growth": "Growth — $299/mo",
}

PLAN_NEXT_STEPS = {
    "pay_per_lead": "You are on the <strong>Pay Per Lead</strong> plan. No monthly fee — you only pay when we deliver a lead. Your card will be saved for automatic billing.",
    "starter": "You selected the <strong>Starter Plan ($149/mo)</strong>. Up to 10 exclusive leads per month at a discounted rate. You will be redirected to complete your payment.",
    "growth": "You selected the <strong>Growth Plan ($299/mo)</strong>. Up to 25 exclusive leads per month at our best rate. You will be redirected to complete your payment.",
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
    <h2 style="color:#fff;margin-top:0;">Welcome, {business_name}! 🎉</h2>
    <p style="color:#c9d1d9;line-height:1.6;">
      Your LeadFlow360 account is live. Our AI agents are now scanning for exclusive
      <strong style="color:#00d4ff;">{service_type}</strong> leads in
      <strong style="color:#00d4ff;">{city}</strong>.
    </p>
    <div style="background:#0d1117;border-radius:8px;padding:16px;margin:20px 0;">
      <p style="color:#00d4ff;margin:0 0 8px;font-weight:bold;">📋 Your Plan: {plan_label}</p>
      <p style="color:#c9d1d9;margin:0;">{plan_note}</p>
    </div>
    <div style="background:#0d1117;border-radius:8px;padding:20px;margin:20px 0;">
      <h3 style="color:#00d4ff;margin-top:0;">What happens next:</h3>
      <ul style="color:#c9d1d9;line-height:1.8;padding-left:20px;">
        <li>Complete your card setup in your dashboard to activate lead delivery</li>
        <li>Our AI scans thousands of sources for active buyers</li>
        <li>Leads are qualified and verified before delivery</li>
        <li>You receive <strong>exclusive leads</strong> — no sharing with competitors</li>
        <li>Expect your <strong>first lead within 24 hours</strong></li>
      </ul>
    </div>
    <div style="text-align:center;margin-top:24px;">
      <a href="https://leadflow360.ca/dashboard.html" style="background:#00d4ff;color:#06101b;padding:14px 32px;border-radius:8px;text-decoration:none;font-weight:bold;display:inline-block;">
        Go to My Dashboard
      </a>
    </div>
    <p style="color:#8b949e;font-size:13px;margin-top:25px;">
      Questions? Reply to this email or contact us at
      <a href="mailto:leads@leadflow360.ca" style="color:#00d4ff;">leads@leadflow360.ca</a>
    </p>
  </div>
  <p style="text-align:center;color:#8b949e;font-size:12px;margin-top:20px;">
    &copy; 2026 LeadFlow360 | leadflow360.ca
  </p>
</div>
</body></html>
"""
        msg.attach(MIMEText(html, 'html'))
        import ssl
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ctx) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASS or settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())
        log.info("welcome_email_sent", to=to_email)
    except Exception as e:
        log.error("welcome_email_failed", error=str(e))


# ------------------------------------------------------------------ #
#  Routes                                                              #
# ------------------------------------------------------------------ #

@router.post("/register")
async def register(data: BusinessRegister, db: AsyncSession = Depends(get_db)):
    repo = BusinessRepository(db)
    if await repo.get_by_email(data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    if data.plan not in ("pay_per_lead", "starter", "growth"):
        raise HTTPException(status_code=400, detail="Invalid plan. Choose: pay_per_lead, starter, growth")

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
    })
    token = create_access_token({"sub": business.id})

    _send_welcome_email(
        to_email=data.email,
        business_name=data.name,
        service_type=str(data.service_type.value if hasattr(data.service_type, 'value') else data.service_type),
        city=data.city,
        plan=data.plan,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "business_id": business.id,
        "plan": data.plan,
        "needs_card_setup": True,
    }


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
    }


@router.get("/dashboard")
async def dashboard(
    db: AsyncSession = Depends(get_db),
    business_id: str = Depends(get_current_business),
):
    from sqlalchemy import select
    from app.db.models import LeadAssignment, Lead, Subscription
    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business:
        raise HTTPException(status_code=404, detail="Not found")

    # Fetch assigned leads
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

    # Fetch active subscription
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
