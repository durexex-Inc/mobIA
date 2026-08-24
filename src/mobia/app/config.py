from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://mobia:mobia@localhost:5433/mobia"
    redis_url: str = "redis://localhost:6380/0"

    whatsapp_app_secret: str = "dev-app-secret"
    whatsapp_verify_token: str = "dev-verify-token"

    # 32 bytes em base64. O default so serve para desenvolvimento e teste --
    # em producao vem do ambiente, como o whatsapp_app_secret.
    content_encryption_key: str = "ZGV2LWtleS0zMi1ieXRlcy1mb3ItbW9iaWEtb2shISE="

    log_level: str = "INFO"

    sweep_received_after_seconds: int = 30
    sweep_inflight_after_seconds: int = 300
    sweep_max_attempts: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
