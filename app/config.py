"""Application settings, loaded from environment variables / .env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MetaTrader 5 terminal ------------------------------------------------
    mt5_login: int | None = None
    mt5_password: SecretStr | None = None
    mt5_server: str | None = None
    # Absolute path to terminal64.exe. Optional: MetaTrader5.initialize() finds
    # the last-used terminal on its own when this is empty.
    mt5_terminal_path: str | None = None
    mt5_portable: bool = False
    mt5_timeout_ms: int = 60_000
    # Connect to the terminal during app startup instead of on first request.
    mt5_connect_on_startup: bool = True

    # --- HTTP API -------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8443
    # Comma-separated list. Every request must send one of these as X-API-Key.
    api_keys: str = ""
    cors_origins: str = ""
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None
    ssl_keyfile_password: SecretStr | None = None
    # Refuse to boot over plain HTTP unless this is set explicitly.
    allow_insecure_http: bool = False

    # --- Trading guard rails --------------------------------------------------
    # The bridge refuses to trade on anything that is not a demo account unless
    # this is flipped on deliberately.
    allow_live_trading: bool = False
    max_volume: float = Field(default=1.0, gt=0)
    default_deviation: int = Field(default=20, ge=0)
    default_magic: int = 20260816
    order_comment_prefix: str = "fastapi-bridge"

    @field_validator("mt5_terminal_path", "ssl_certfile", "ssl_keyfile", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def api_key_list(self) -> list[str]:
        return [key.strip() for key in self.api_keys.split(",") if key.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def tls_enabled(self) -> bool:
        return bool(self.ssl_certfile and self.ssl_keyfile)

    @property
    def has_credentials(self) -> bool:
        return bool(self.mt5_login and self.mt5_password and self.mt5_server)


@lru_cache
def get_settings() -> Settings:
    return Settings()
