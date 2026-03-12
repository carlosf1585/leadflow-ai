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

    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""

    GOOGLE_MAPS_API_KEY: str = ""

    LEAD_PRICE_PLUMBING: float = 35.0
    LEAD_PRICE_ROOFING: float = 45.0
    LEAD_PRICE_HVAC: float = 40.0
    LEAD_PRICE_PEST_CONTROL: float = 25.0
    LEAD_PRICE_DENTAL: float = 80.0
    LEAD_PRICE_AUTO_ACCIDENT: float = 300.0
    LEAD_PRICE_DEFAULT: float = 35.0

    DISCOVERY_CITIES: List[str] = ["New York", "Los Angeles", "Houston", "Phoenix", "Chicago"]
    SERVICE_CATEGORIES: List[str] = ["plumber", "roofer", "hvac", "pest control", "dentist"]

    CORS_ORIGINS: List[str] = ["*"]
    ADMIN_TOKEN: str = "change-me-admin-token"

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
