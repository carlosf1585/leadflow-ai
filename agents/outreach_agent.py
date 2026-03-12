import asyncio
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog
from openai import AsyncOpenAI

from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import BusinessStatus
from app.db.repositories.business_repo import BusinessRepository

log = structlog.get_logger()
QUEUE_OUTREACH = "queue:outreach"


class OutreachAgent(BaseAgent):
    name = "outreach_agent"
    queue = QUEUE_OUTREACH

    def __init__(self):
        super().__init__()
        self.openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def _generate_email(self, business_name, niche, city):
        msg = await self.openai.chat.completions.create(
            model=settings.OPENAI_MODEL_FAST,
            max_tokens=300,
            messages=[{"role": "user", "content": f"Write a short cold email to {business_name} ({niche} in {city}). Offer 3 FREE leads. Under 80 words. Format: Subject: <subject>\n\n<body>"}],
        )
        text = msg.choices[0].message.content.strip()
        lines = text.split("\n\n", 1)
        subject = lines[0].replace("Subject:", "").strip()
        body = lines[1].strip() if len(lines) > 1 else text
        return subject, body

    def _send_email(self, to_email, subject, body):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_USER
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as s:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            s.sendmail(settings.SMTP_USER, to_email, msg.as_string())

    async def process(self, payload: dict):
        subject, body = await self._generate_email(
            payload["business_name"], payload.get("niche", "service"), payload.get("city", "your city")
        )
        try:
            self._send_email(payload["business_email"], subject, body)
            log.info("Outreach sent", business=payload["business_name"])
        except Exception as e:
            log.error("Email failed", error=str(e))
            return
        async with AsyncSessionLocal() as db:
            repo = BusinessRepository(db)
            await repo.update_status(payload["business_id"], BusinessStatus.CONTACTED)
            await db.commit()


if __name__ == "__main__":
    asyncio.run(OutreachAgent().run())
