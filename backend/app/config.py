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

    # ---- ML layer (app/ml) -------------------------------------------------
    # Every ML component degrades gracefully to the deterministic rules in
    # app/recovery/rules.py when disabled, missing, or failing.
    ml_enabled: bool = True
    ml_artifact_dir: str | None = None            # default: app/ml/artifacts
    ml_local_utc_offset_minutes: int = 330        # IST; used for hour-of-day / salary-window features
    ml_sandbox_world: str = "base"               # Test-Mode ground truth: "base" | "shifted" | "conservative" (watch the bandit adapt)
    ml_history_fetch_limit: int = 300             # recent payments pulled once per scan for features + anomaly checks

    ml_bandit_enabled: bool = True
    ml_bandit_arms_hours: list[float] = [0.25, 6.0, 12.0, 24.0, 48.0, 72.0]
    ml_bandit_prior_strength: float = 4.0         # pseudo-observations behind the weak prior
    ml_immediate_threshold_hours: float = 0.5     # chosen delays <= this execute right away

    ml_anomaly_enabled: bool = True
    ml_fraud_window_minutes: int = 60
    ml_fraud_min_failures: int = 3                # minimum evidence before any security hold
    ml_outage_window_minutes: int = 60
    ml_outage_baseline_days: int = 7
    ml_outage_min_attempts: int = 8
    ml_outage_alpha: float = 1e-4                 # exact-binomial p-value threshold (multiplicity-aware)
    ml_outage_hold_minutes: int = 60              # how far a deferred retry is pushed out
    ml_outage_alert_ttl_minutes: int = 120
    ml_max_outage_deferrals: int = 6              # bounded: never defer a case forever


@lru_cache
def get_settings() -> Settings:
    return Settings()
