import base64

import pytest

from mobia.app.config import (
    CHAVE_DE_DESENVOLVIMENTO,
    ConfiguracaoInsegura,
    Settings,
    get_settings,
)


def test_settings_le_do_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "segredo-do-teste")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6390/1")
    settings = Settings(_env_file=None)
    assert settings.whatsapp_app_secret == "segredo-do-teste"
    assert settings.redis_url == "redis://localhost:6390/1"


def test_get_settings_e_cacheada() -> None:
    get_settings.cache_clear()
    assert get_settings() is get_settings()


def test_limiares_do_sweeper_tem_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.sweep_received_after_seconds == 30
    assert settings.sweep_inflight_after_seconds == 300
    assert settings.sweep_max_attempts == 5


def test_producao_com_a_chave_de_desenvolvimento_nao_sobe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chave de cifra errada nao falha alto como assinatura errada falha.

    Ela grava o dado com uma chave publicamente conhecida e nada reclama. A
    exposicao mais afiada e a migration 0004, que cifraria a tabela inteira num
    job de CI/CD que subiu sem o segredo.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ConfiguracaoInsegura) as erro:
        Settings(_env_file=None)

    assert "CONTENT_ENCRYPTION_KEY" in str(erro.value)
    assert CHAVE_DE_DESENVOLVIMENTO not in str(erro.value)


def test_producao_com_chave_propria_sobe(monkeypatch: pytest.MonkeyPatch) -> None:
    chave = base64.b64encode(b"x" * 32).decode()
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CONTENT_ENCRYPTION_KEY", chave)
    settings = Settings(_env_file=None)
    assert settings.content_encryption_key == chave


def test_desenvolvimento_segue_com_o_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A guarda nao pode travar a maquina de ninguem nem o CI."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)
    assert settings.environment == "development"
    assert settings.content_encryption_key == CHAVE_DE_DESENVOLVIMENTO
