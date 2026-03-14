import enum
from datetime import datetime
from sqlalchemy import Column, String, Float, Boolean, DateTime, Integer, Enum, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class ServiceType(str, enum.Enum):
    PLUMBING = "plumbing"
    ROOFING = "roofing"
    HVAC = "hvac"
    PEST_CONTROL = "pest_control"
    DENTAL = "dental"
    AUTO_ACCIDENT = "auto_accident"
    OTHER = "other"


class LeadStatus(str, enum.Enum):
    PENDING = "pending"
    QUALIFIED = "qualified"
    ROUTED = "routed"
    CHARGED = "charged"
    SPAM = "spam"
    REJECTED = "rejected"


class BusinessStatus(str, enum.Enum):
    PROSPECT = "prospect"
    CONTACTED = "contacted"
    ACTIVE = "active"
    CHURNED = "churned"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    PAST_DUE = "past_due"


class Business(Base):
    __tablename__ = "businesses"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String)
    address = Column(String)
    city = Column(String)
    state = Column(String)
    zip_code = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    service_type = Column(Enum(ServiceType), nullable=False)
    status = Column(Enum(BusinessStatus), default=BusinessStatus.PROSPECT)
    hashed_password = Column(String)

    # Billing plan: pay_per_lead | starter | growth
    plan = Column(String, default="pay_per_lead")

    stripe_customer_id = Column(String)
    stripe_payment_method_id = Column(String)

    ai_score = Column(Float, default=0.0)
    website = Column(String)
    google_place_id = Column(String, unique=True)
    rating = Column(Float)
    review_count = Column(Integer, default=0)
    niche = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    leads = relationship("LeadAssignment", back_populates="business")
    subscriptions = relationship("Subscription", back_populates="business")
    outreach_campaigns = relationship("OutreachCampaign", back_populates="business")


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True)
    consumer_name = Column(String, nullable=False)
    consumer_email = Column(String)
    consumer_phone = Column(String, nullable=False)
    service_type = Column(Enum(ServiceType), nullable=False)
    description = Column(Text)
    city = Column(String, nullable=False)
    state = Column(String)
    zip_code = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    status = Column(Enum(LeadStatus), default=LeadStatus.PENDING)
    ai_score = Column(Float, default=0.0)
    urgency = Column(Boolean, default=False)
    spam_flag = Column(Boolean, default=False)
    price = Column(Float)
    niche = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignments = relationship("LeadAssignment", back_populates="lead")


class LeadAssignment(Base):
    __tablename__ = "lead_assignments"

    id = Column(String, primary_key=True)
    lead_id = Column(String, ForeignKey("leads.id"), nullable=False)
    business_id = Column(String, ForeignKey("businesses.id"), nullable=False)
    price = Column(Float, nullable=False)
    distance_km = Column(Float)
    charged = Column(Boolean, default=False)
    stripe_payment_intent_id = Column(String)
    assigned_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("Lead", back_populates="assignments")
    business = relationship("Business", back_populates="leads")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String, primary_key=True)
    business_id = Column(String, ForeignKey("businesses.id"), nullable=False)
    stripe_subscription_id = Column(String, unique=True)
    status = Column(Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE)
    plan = Column(String, default="starter")  # starter | growth
    monthly_lead_limit = Column(Integer, default=10)
    leads_used_this_month = Column(Integer, default=0)
    price_per_month = Column(Float, default=149.0)
    started_at = Column(DateTime, default=datetime.utcnow)
    cancelled_at = Column(DateTime)

    business = relationship("Business", back_populates="subscriptions")


class OutreachCampaign(Base):
    __tablename__ = "outreach_campaigns"

    id = Column(String, primary_key=True)
    business_id = Column(String, ForeignKey("businesses.id"), nullable=False)
    sequence_step = Column(Integer, default=1)
    email_sent = Column(Boolean, default=False)
    response_received = Column(Boolean, default=False)
    response_text = Column(Text)
    converted = Column(Boolean, default=False)
    sent_at = Column(DateTime)
    next_follow_up = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("Business", back_populates="outreach_campaigns")


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id = Column(String, primary_key=True)
    agent_name = Column(String, nullable=False)
    action = Column(String, nullable=False)
    status = Column(String, default="success")
    details = Column(JSON)
    duration_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class RevenueEvent(Base):
    __tablename__ = "revenue_events"

    id = Column(String, primary_key=True)
    business_id = Column(String, ForeignKey("businesses.id"))
    amount = Column(Float, nullable=False)
    event_type = Column(String, nullable=False)
    lead_id = Column(String, ForeignKey("leads.id"))
    stripe_payment_intent_id = Column(String)
    niche = Column(String)
    city = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
