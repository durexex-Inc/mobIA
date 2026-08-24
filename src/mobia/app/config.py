from decimal import Decimal
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


# Preco em dolar por 1 milhao de tokens, (entrada, saida). O custo e calculado e
# **materializado** no momento do registro: mudar um preco aqui amanha nao pode
# reescrever o que ja foi gasto.
#
# claude-sonnet-5 esta com tarifa promocional de 2.00/10.00 ate 2026-08-31.
# Fica a tarifa cheia de proposito: precificacao com vigencia por data exigiria
# intervalos de data na tabela, que o spec rejeitou ao descartar a opcao de
# calcular custo em query. Superestimar num painel de custo e mais seguro que
# subestimar.
PRECOS_POR_MODELO: dict[str, tuple[Decimal, Decimal]] = {
    "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
    "claude-sonnet-5": (Decimal("3.00"), Decimal("15.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}
