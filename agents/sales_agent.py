import asyncio
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select

from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Business, OutreachCampaign

log = structlog.get_logger()
QUEUE_SALES = "queue:sales"


class SalesAgent(BaseAgent):
    name = "sales_agent"
    queue = QUEUE_SALES

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    def _send_email(self, to_email, subject, body):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))
        context = ssl.create_default_context()
        try:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as s:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.sendmail(settings.SMTP_USER, to_email, msg.as_string())
        except Exception as e:
            log.error("Email failed", error=str(e))

    async def _generate_sequence_email(self, business_name, niche, city, step):
        ctx = {1: "First cold outreach. Offer 3 free leads.", 3: "Follow-up. Competitor in city already signed up.", 7: "Final last chance email."}
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_FAST,
            max_tokens=300,
            messages=[{"role": "user", "content": f"Sales email step {step} for {business_name} ({niche} in {city}). Context: {ctx.get(step, '')}. LeadFlow AI sends them paying customers. Under 80 words. Format: Subject: <subject>\n\n<body>"}],
        )
        text = msg.choices[0].message.content.strip()
        lines = text.split("\n\n", 1)
        subject = lines[0].replace("Subject:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else text
        return subject, body

    async def process(self, payload: dict):
        action = payload.get("action")
        if action == "run_sequences":
            async with AsyncSessionLocal() as db:
                now = datetime.utcnow()
                result = await db.execute(
                    select(OutreachCampaign).where(
                        OutreachCampaign.next_follow_up <= now,
                        OutreachCampaign.converted == False,
                        OutreachCampaign.sequence_step <= 7,
                    )
                )
                campaigns = result.scalars().all()
                for campaign in campaigns:
                    business = await db.get(Business, campaign.business_id)
                    if not business:
                        continue
                    subject, body = await self._generate_sequence_email(
                        business.name, business.niche or "service", business.city or "your city", campaign.sequence_step
                    )
                    self._send_email(business.email, subject, body)
                    next_steps = {1: 3, 3: 7}
                    next_step = next_steps.get(campaign.sequence_step)
                    if next_step:
                        campaign.next_follow_up = now + timedelta(days=2)
                        campaign.sequence_step = next_step
                    else:
                        campaign.sequence_step = 99
                    campaign.email_sent = True
                    campaign.sent_at = now
                await db.commit()
                log.info("Sales sequences run", count=len(campaigns))


if __name__ == "__main__":
    asyncio.run(SalesAgent().run())
