from typing import List
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ENV: str = "production"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    DATABASE_URL: str = "postgresql+asyncpg://leadflow:leadflow@postgres:5432/leadflow"
    REDIS_URL: str = "redis://redis:6379/0"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL_FAST: str = "gpt-4o-mini"
    OPENAI_MODEL_SMART: str = "gpt-4o"

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""

    STRIPE_PRICE_STARTER: str = ""
    STRIPE_PRICE_GROWTH: str = ""

    SMTP_HOST: str = "smtp.hostinger.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_PASS: str = ""

    RESEND_API_KEY: str = ""

    GOOGLE_MAPS_API_KEY: str = ""

    GOOGLE_ADS_DEVELOPER_TOKEN: str = ""
    GOOGLE_ADS_CLIENT_ID: str = ""
    GOOGLE_ADS_CLIENT_SECRET: str = ""
    GOOGLE_ADS_REFRESH_TOKEN: str = ""
    GOOGLE_ADS_MANAGER_CUSTOMER_ID: str = ""
    GOOGLE_ADS_CUSTOMER_ID: str = ""

    LEAD_PRICE_PLUMBING: float = 45.0
    LEAD_PRICE_ROOFING: float = 55.0
    LEAD_PRICE_HVAC: float = 50.0
    LEAD_PRICE_PEST_CONTROL: float = 35.0
    LEAD_PRICE_DENTAL: float = 95.0
    LEAD_PRICE_AUTO_ACCIDENT: float = 350.0
    LEAD_PRICE_DEFAULT: float = 45.0

    LEAD_PRICE_STARTER_PLUMBING: float = 35.0
    LEAD_PRICE_STARTER_ROOFING: float = 42.0
    LEAD_PRICE_STARTER_HVAC: float = 38.0
    LEAD_PRICE_STARTER_DENTAL: float = 75.0
    LEAD_PRICE_STARTER_DEFAULT: float = 35.0

    LEAD_PRICE_GROWTH_PLUMBING: float = 28.0
    LEAD_PRICE_GROWTH_ROOFING: float = 35.0
    LEAD_PRICE_GROWTH_HVAC: float = 30.0
    LEAD_PRICE_GROWTH_DENTAL: float = 60.0
    LEAD_PRICE_GROWTH_DEFAULT: float = 28.0

    PLAN_STARTER_MONTHLY_LEADS: int = 10
    PLAN_STARTER_PRICE_MONTH: float = 149.0
    PLAN_GROWTH_MONTHLY_LEADS: int = 25
    PLAN_GROWTH_PRICE_MONTH: float = 299.0

    DISCOVERY_CITIES: List[str] = ["Toronto", "Vancouver", "Calgary", "Ottawa", "Montreal"]
    SERVICE_CATEGORIES: List[str] = ["plumber", "roofer", "hvac", "pest control", "dentist"]

    CORS_ORIGINS: List[str] = ["*"]
    ADMIN_TOKEN: str = "change-me-admin-token"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
