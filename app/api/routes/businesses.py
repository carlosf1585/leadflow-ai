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


def _send_welcome_email(to_email: str, business_name: str, service_type: str, city: str):
    """Send a welcome email to the new business registration."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f'Welcome to LeadFlow360 - Your leads are coming!'
        msg['From'] = f'LeadFlow360 <{settings.SMTP_FROM}>'
        msg['To'] = to_email

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
              Your LeadFlow360 account has been created successfully. Our AI agents are now
              being configured to find exclusive <strong style="color:#00d4ff;">{service_type}</strong>
              leads in <strong style="color:#00d4ff;">{city}</strong>.
            </p>
            <div style="background:#0d1117;border-radius:8px;padding:20px;margin:20px 0;">
              <h3 style="color:#00d4ff;margin-top:0;">What happens next:</h3>
              <ul style="color:#c9d1d9;line-height:1.8;padding-left:20px;">
                <li>Our AI scans thousands of sources for active buyers</li>
                <li>Leads are qualified and verified before delivery</li>
                <li>You receive exclusive leads — no sharing with competitors</li>
                <li>Expect your <strong>first lead within 24 hours</strong></li>
              </ul>
            </div>
            <div style="background:#0d4a2e;border:1px solid #196b38;border-radius:8px;padding:15px;margin:20px 0;">
              <p style="color:#3fb950;margin:0;font-weight:bold;">✅ Account Active</p>
              <p style="color:#c9d1d9;margin:5px 0 0;">Service: {service_type.title()} | City: {city}</p>
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

        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASS)
            server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())

        log.info("welcome_email_sent", to=to_email)
    except Exception as e:
        log.error("welcome_email_failed", error=str(e))


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
    # Send welcome email (non-blocking — errors are logged, not raised)
    _send_welcome_email(
        to_email=data.email,
        business_name=data.name,
        service_type=str(data.service_type.value if hasattr(data.service_type, 'value') else data.service_type),
        city=data.city,
    )
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
