import asyncio
import stripe
import structlog
from agents.base_agent import BaseAgent
from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import LeadAssignment, LeadStatus
from app.db.repositories.analytics_repo import AnalyticsRepository
from app.db.repositories.business_repo import BusinessRepository
from app.db.repositories.lead_repo import AssignmentRepository, LeadRepository

log = structlog.get_logger()
QUEUE_BILLING = "queue:billing"
QUEUE_ANALYTICS = "queue:analytics"
stripe.api_key = settings.STRIPE_SECRET_KEY


class BillingAgent(BaseAgent):
    name = "billing_agent"
    queue = QUEUE_BILLING

    async def process(self, payload: dict):
        assignment_id = payload["assignment_id"]
        lead_id = payload["lead_id"]
        price = float(payload["price"])
        async with AsyncSessionLocal() as db:
            biz_repo = BusinessRepository(db)
            lead_repo = LeadRepository(db)
            assign_repo = AssignmentRepository(db)
            assignment = await db.get(LeadAssignment, assignment_id)
            if not assignment or assignment.charged:
                return
            business = await biz_repo.get_by_id(assignment.business_id)
            if not business or not business.stripe_customer_id:
                log.warning("No Stripe customer", business_id=assignment.business_id)
                return
            try:
                intent = stripe.PaymentIntent.create(
                    amount=int(price * 100),
                    currency="usd",
                    customer=business.stripe_customer_id,
                    payment_method=business.stripe_payment_method_id,
                    confirm=True,
                    off_session=True,
                    description=f"Lead {lead_id}",
                )
                await assign_repo.mark_charged(assignment_id, intent["id"])
                await lead_repo.update_status(lead_id, LeadStatus.CHARGED)
                await db.commit()
                await self.publish(QUEUE_ANALYTICS, {
                    "action": "record_revenue",
                    "business_id": business.id,
                    "lead_id": lead_id,
                    "amount": price,
                    "event_type": "lead_charge",
                    "niche": business.niche,
                    "city": business.city,
                    "stripe_payment_intent_id": intent["id"],
                })
                log.info("Charged", lead_id=lead_id, amount=price)
            except stripe.error.CardError as e:
                log.warning("Card declined", error=str(e))
            except stripe.error.StripeError as e:
                log.error("Stripe error", error=str(e))


if __name__ == "__main__":
    asyncio.run(BillingAgent().run())
