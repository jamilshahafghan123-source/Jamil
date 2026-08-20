"""Application configuration.

Every secret is read from the environment. Nothing is hard-coded, and no
default is ever a real credential. In Google Cloud these come from Secret
Manager, surfaced to Cloud Run as environment variables.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ---- Core -----------------------------------------------------------
    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # ---- Database -------------------------------------------------------
    # postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str

    # ---- Auth -----------------------------------------------------------
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 60
    # Bootstrap user, created on first startup only if no users exist.
    BOOTSTRAP_EMAIL: str | None = None
    BOOTSTRAP_PASSWORD: str | None = None

    # ---- CORS -----------------------------------------------------------
    # Comma-separated exact origins. "*" is rejected in prod.
    CORS_ORIGINS: str = "http://localhost:5173"

    # ---- MT5 bridge -----------------------------------------------------
    # URL of the bridge running on the Windows VM alongside the MT5 terminal.
    MT5_BRIDGE_URL: str = "http://127.0.0.1:8100"
    # Shared secret; the bridge rejects any request without it.
    MT5_BRIDGE_TOKEN: str
    MT5_BRIDGE_TIMEOUT: float = 15.0

    # ---- Windows recovery agent -----------------------------------------
    # Small trusted service beside MT5/Docker on the Windows host. Empty by
    # default: with no URL or token, recovery reports "not configured" and
    # attempts nothing, so a deployment without an agent behaves exactly as
    # it does today. Bind it to localhost or a private network; it is never
    # meant to be publicly reachable.
    WINDOWS_AGENT_URL: str | None = None
    # Deliberately a different secret from MT5_BRIDGE_TOKEN, so neither
    # one's rotation or compromise touches the other.
    WINDOWS_AGENT_TOKEN: str | None = None

    # ---- Trading --------------------------------------------------------
    SYMBOL: str = "XAUUSD"

    # THE REAL-MONEY KILL SWITCH.
    # Must be true *and* the user must explicitly arm REAL mode through the
    # API before a single live order can be sent. Ships false.
    ALLOW_REAL_TRADING: bool = False

    # ---- AI analyst -----------------------------------------------------
    ANTHROPIC_API_KEY: str | None = None
    ANALYST_MODEL: str = "claude-opus-5"
    ANALYST_EFFORT: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ANALYST_MAX_TOKENS: int = 8000
    # Bars of history handed to the indicator engine per timeframe.
    BARS_PER_TF: int = 300

    # ---- Rate limiting --------------------------------------------------
    RATE_LIMIT_PER_MINUTE: int = 120
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # ---- Bot loop -------------------------------------------------------
    BOT_INTERVAL_SECONDS: int = 60
    MARKET_POLL_SECONDS: float = 2.0

    @field_validator("DATABASE_URL")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        # Accept the plain postgres URL Cloud SQL hands out and upgrade it.
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    if s.ENV == "prod" and "*" in s.cors_origins:
        raise RuntimeError("CORS_ORIGINS must not contain '*' in prod")
    if s.ENV == "prod" and len(s.JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must be >= 32 chars in prod")
    return s


settings = get_settings()
