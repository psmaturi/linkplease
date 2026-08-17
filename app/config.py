"""
config.py — centralised, environment-based configuration.

Why pydantic-settings:
  All env vars are validated at startup. If a required variable is missing,
  the app crashes immediately with a clear error instead of failing at runtime
  inside a request handler.

Why not os.getenv() scattered around the codebase:
  A single config object is easy to mock in tests and easy to audit.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── External API ──────────────────────────────────────────────────────────
    pseudogram_api_key: str
    pseudogram_base_url: str = "https://pseudogram-api.onrender.com"

    # ── Webhook signature ─────────────────────────────────────────────────────
    # HMAC-SHA256 secret for verifying X-PseudoGram-Signature.
    # PseudoGram uses the same API key as the signing secret.
    webhook_secret: str

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://linkplease:linkplease_dev@localhost:5432/linkplease"
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── App behaviour ─────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # Maximum number of delivery attempts before permanently marking as failed.
    max_dm_retries: int = 5

    # How often the reconciliation worker polls PseudoGram for DM status.
    reconciliation_interval_seconds: int = 60

    # Rate limit imposed by PseudoGram (requests per window).
    pseudogram_rate_limit: int = 10
    pseudogram_rate_window_seconds: int = 60

    # Redis key for the delivery queue (list of dm_attempt UUIDs)
    delivery_queue_key: str = "delivery_q"

    # Redis key for rate-limit tracking (sorted set of timestamps)
    rate_limit_key: str = "rate_limit:pseudogram"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Module-level singleton — import this everywhere.
settings = Settings()
