import base64

import pytest

from mobia.app.config import (
    CHAVE_DE_DESENVOLVIMENTO,
    ConfiguracaoInsegura,
    Settings,
    get_settings,
)
from mobia.infra.anthropic import get_client


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


def test_defaults_da_janela_de_contexto(settings) -> None:
    """Os numeros da RN-02.2 e RN-02.5 vivem em configuracao, nao espalhados no codigo."""
    assert settings.modelo_resumo == "claude-opus-5"
    assert settings.contexto_teto_de_tokens == 12000
    assert settings.contexto_literais_minimas == 20
    assert settings.contexto_gatilho_de_regeneracao == 40


def test_gatilho_deixa_o_piso_de_literais(settings) -> None:
    """Dobrar `gatilho - minimas` deixa exatamente `minimas` literais.

    Quem garante o piso e `dividir`, nao esta relacao: com `piso_pode_ceder`
    desligado ela nunca dobra abaixo de `minimas`, seja qual for o gatilho. O
    que esta relacao controla e a *frequencia* -- com um gatilho menor que
    `2 * minimas` a dobra sobra pouco a dobrar e a conversa paga uma chamada de
    modelo com muito mais frequencia, cada uma absorvendo pouquissima mensagem.
    Com `gatilho >= 2 * minimas` cada regeneracao dobra pelo menos `minimas`
    mensagens de uma vez, que e o custo por mensagem que o spec orcou.
    """
    assert settings.contexto_gatilho_de_regeneracao >= 2 * settings.contexto_literais_minimas


def test_headroom_desconta_do_teto(settings) -> None:
    """O teto comparado nao e o teto nominal.

    A contagem mede um proxy menor do que a TEC-134 vai de fato enviar: uma
    mensagem plana, sem system e sem o overhead estrutural de cada turno do
    array. A reserva e o que impede o modulo aceitar um contexto que so estoura
    na requisicao real.
    """
    assert settings.contexto_headroom_de_tokens > 0
    assert settings.teto_de_tokens_efetivo == (
        settings.contexto_teto_de_tokens - settings.contexto_headroom_de_tokens
    )
    assert settings.teto_de_tokens_efetivo < settings.contexto_teto_de_tokens


def test_limiar_deriva_do_teto_efetivo(settings) -> None:
    """Mexer no teto ou na reserva move o limiar junto, sem descasar em silencio."""
    assert settings.limiar_de_contagem_efetivo < settings.teto_de_tokens_efetivo


def test_cliente_recusa_subir_sem_chave(monkeypatch, caches_de_cliente_limpos: None) -> None:
    """Chave ausente falha aqui, com mensagem util, e nao no meio de um turno."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ConfiguracaoInsegura, match="ANTHROPIC_API_KEY"):
        get_client()


def test_cliente_e_construido_uma_vez(monkeypatch, caches_de_cliente_limpos: None) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")

    assert get_client() is get_client()


def test_defaults_do_agente(settings) -> None:
    """O modelo do agente e configuravel separado do modelo do resumo.

    Sao trabalhos diferentes: a TEC-210 vai querer afinar a acuracia de
    intencao sem mexer na qualidade do resumo, e vice-versa.
    """
    assert settings.modelo_agente == "claude-opus-5"
    assert settings.whatsapp_api_base.startswith("https://")


def test_token_da_meta_nao_tem_default_utilizavel(settings) -> None:
    """Sem default utilizavel: quem sobe sem configurar tem de decidir.

    Ao contrario da ANTHROPIC_API_KEY, a ausencia nao falha alto sozinha --
    vira 401 da Meta, tratado como falha permanente. A guarda que impede isso
    de chegar a producao fica em `mobia.workers.main.startup`, testada em
    `tests/integration/test_worker_startup.py`.
    """
    assert settings.whatsapp_access_token == ""


def test_cliente_falha_tipado_antes_de_o_arq_cancelar(
    monkeypatch, caches_de_cliente_limpos: None
) -> None:
    """O teto por requisicao tem de caber no `job_timeout` do worker.

    O default do SDK (10 min, com retentativa interna) e maior que o job
    inteiro: uma chamada lenta nunca falharia, seria cancelada pelo ARQ. E
    `CancelledError` e BaseException -- o `except Exception` de
    `process_message` nao pega, a linha nao vira FAILED e a reserva de envio
    fica presa. Erro tipado e recuperavel; cancelamento nao e.
    """
    from mobia.infra.anthropic import MAX_TENTATIVAS, TIMEOUT_SEGUNDOS
    from mobia.workers.main import WorkerSettings

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    cliente = get_client()

    assert cliente.timeout == TIMEOUT_SEGUNDOS
    assert cliente.max_retries == MAX_TENTATIVAS
    pior_caso_por_chamada = TIMEOUT_SEGUNDOS * (1 + MAX_TENTATIVAS)
    # Duas chamadas pesadas (resumir + classificar) no turno com dobra.
    assert pior_caso_por_chamada * 2 <= WorkerSettings.job_timeout
