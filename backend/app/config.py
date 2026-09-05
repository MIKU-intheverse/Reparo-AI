"""
Central configuration for Reparo AI backend.

Every environment-dependent value lives here. Nothing else in the codebase
reads os.environ directly. This file only ever holds APPLICATION-level
secrets (DB url, JWT signing key, encryption key, SMTP creds, AI key,
webhook secret) — never a user's Razorpay Key Secret. Those live encrypted
in the database, one row per user, and are decrypted only inside
providers/razorpay_provider.py at the moment of an outbound API call.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Reparo AI"
    environment: str = "development"

    database_url: str = "sqlite:///./reparo.db"

    auth_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7


    encryption_key: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "Reparo AI <no-reply@reparo.ai>"

    razorpay_webhook_secret: str | None = None

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"

    allowed_origins: list[str] = ["http://localhost:3000"]


    recovery_max_retries: int = 3
    recovery_max_communications: int = 3
    recovery_cooldown_hours: float = 6.0
    recovery_window_days: float = 7.0
    recovery_soft_decline_retry_hours: float = 18.0
    recovery_technical_retry_hours: float = 0.25
    recovery_hard_decline_retry_hours: float = 0.0
    recovery_max_cases_per_scan: int = 25
    recovery_min_probability: float = 0.08


@lru_cache
def get_settings() -> Settings:
    return Settings()
