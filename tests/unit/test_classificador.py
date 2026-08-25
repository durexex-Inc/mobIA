import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mobia.domain.agente import classificador as classificador_mod
from mobia.domain.agente.classificador import ClassificadorAnthropic, RespostaInvalida
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.montagem import ContextoMontado

# Strings que nao podem, sob nenhuma circunstancia, sobreviver ao log nem a
# uma excecao. Se um destes valores aparecer em `caplog.text` ou em
# `str(erro.value)`, o boundary vazou conteudo do lead ou o prompt que o
# gerou -- exatamente o que o `process_message` da TEC-134 grava em
# `messages.last_error` e loga sem a mascara de PII.
TEXTO_DA_RESPOSTA = "SENTINELA-RESPOSTA o apartamento fica na Rua das Palmeiras"
SISTEMA_DO_PROMPT = "SENTINELA-SISTEMA instrucao confidencial do agente"
RESUMO_DO_PROMPT = "SENTINELA-RESUMO lead mora na Rua das Palmeiras, quer 2 quartos"


def _contexto(*, resumo: str | None = RESUMO_DO_PROMPT) -> ContextoMontado:
    return ContextoMontado(
        sistema=SISTEMA_DO_PROMPT,
        resumo=resumo,
        literais=[],
        estado=None,
        tokens=100,
        degradado=False,
    )


def _bloco_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _resposta_falsa(
    *,
    texto: str | None,
    stop_reason: str = "end_turn",
    tokens_in: int = 4000,
    tokens_out: int = 200,
) -> SimpleNamespace:
    blocos = [_bloco_texto(texto)] if texto else []
    return SimpleNamespace(
        content=blocos,
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
        stop_reason=stop_reason,
    )


def _resposta_json(
    *,
    intencao: str = "COMPRA",
    confianca: float = 0.9,
    resposta: str = TEXTO_DA_RESPOSTA,
    stop_reason: str = "end_turn",
) -> SimpleNamespace:
    import json

    texto = json.dumps({"intencao": intencao, "confianca": confianca, "resposta": resposta})
    return _resposta_falsa(texto=texto, stop_reason=stop_reason)


class _ClienteFalso:
    """Dublê minimo do `AsyncAnthropic`: so o que `classificar` toca.

    Nao e um dublê de rede -- e um objeto Python comum que nunca abre socket.
    """

    def __init__(self, resposta: SimpleNamespace) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


def _instalar_cliente_falso(monkeypatch: pytest.MonkeyPatch, resposta: SimpleNamespace) -> None:
    """Troca o `get_client` que `classificador.py` enxerga, nao o global cacheado.

    Mesma tecnica de `test_resumo.py`: o modulo importa `get_client` por nome,
    entao substituir a referencia isola o teste do `@lru_cache` de
    `mobia.infra.anthropic.get_client` e da `ANTHROPIC_API_KEY`.
    """
    monkeypatch.setattr(classificador_mod, "get_client", lambda: _ClienteFalso(resposta))


async def test_classificar_devolve_intencao_confianca_e_resposta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resposta = _resposta_json(intencao="ALUGUEL", confianca=0.75, resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.intencao == Intencao.ALUGUEL
    assert resultado.confianca == pytest.approx(0.75)
    assert resultado.resposta == TEXTO_DA_RESPOSTA
    assert resultado.tokens_in == 4000
    assert resultado.tokens_out == 200


async def test_classificar_loga_metricas_sem_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`agente.turno_gerado` carrega numeros; nunca a resposta nem o prompt."""
    resposta = _resposta_json(resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO):
        await ClassificadorAnthropic().classificar(_contexto())

    assert "agente.turno_gerado" in caplog.text
    assert '"tokens_in"' in caplog.text
    assert '"tokens_out"' in caplog.text
    assert '"custo_usd"' in caplog.text
    assert '"latency_ms"' in caplog.text
    assert '"modelo"' in caplog.text

    # a parte que importa: nem a resposta, nem o sistema, nem o resumo
    # aparecem no log estruturado.
    assert TEXTO_DA_RESPOSTA not in caplog.text
    assert SISTEMA_DO_PROMPT not in caplog.text
    assert RESUMO_DO_PROMPT not in caplog.text


async def test_classificar_recusa_stop_reason_diferente_de_end_turn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    resposta = _resposta_falsa(texto=None, stop_reason="max_tokens")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "max_tokens" in str(erro.value)
    assert "agente.turno_gerado" not in caplog.text


async def test_classificar_recusa_resposta_vazia(monkeypatch: pytest.MonkeyPatch) -> None:
    resposta = _resposta_falsa(texto=None, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "vazia" in str(erro.value)


async def test_classificar_recusa_campo_resposta_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    resposta = _resposta_json(resposta="   ")
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert "vazio" in str(erro.value)


async def test_classificar_recusa_json_invalido_sem_ecoar_o_texto(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A resposta destinada ao lead nunca pode aparecer na mensagem da excecao.

    `process_message` grava `f"{type(exc).__name__}: {exc}"` em
    `messages.last_error` e loga `error=str(exc)` sem a mascara de PII -- o
    texto que o modelo escreveu para o lead nao pode chegar ali por essa
    porta, mesmo quando o JSON vem malformado (ex.: o modelo devolveu prosa
    em vez de JSON, ou um JSON com a resposta cortada no meio).
    """
    texto_malformado = f'{{"intencao": "COMPRA", "confianca": 0.9, "resposta": "{TEXTO_DA_RESPOSTA}'
    resposta = _resposta_falsa(texto=texto_malformado, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert TEXTO_DA_RESPOSTA not in str(erro.value)
    assert TEXTO_DA_RESPOSTA not in caplog.text
    assert "agente.turno_gerado" not in caplog.text


async def test_classificar_recusa_intencao_desconhecida_sem_ecoar_o_texto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valor de `intencao` fora do enum e o mesmo furo que a Task 5 lista

    explicitamente: o modelo pode devolver algo que o schema deveria ter
    impedido. A excecao ainda nao pode carregar `resposta`.
    """
    resposta = _resposta_json(intencao="MUDANCA_DE_PAIS", resposta=TEXTO_DA_RESPOSTA)
    _instalar_cliente_falso(monkeypatch, resposta)

    with pytest.raises(RespostaInvalida) as erro:
        await ClassificadorAnthropic().classificar(_contexto())

    assert TEXTO_DA_RESPOSTA not in str(erro.value)


async def test_classificar_usa_modelo_agente_das_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mobia.app import config as config_mod

    monkeypatch.setattr(config_mod.get_settings(), "modelo_agente", "claude-modelo-de-teste")
    resposta = _resposta_json()
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert resultado.modelo == "claude-modelo-de-teste"
    _, kwargs = cliente.messages.create.call_args
    assert kwargs["model"] == "claude-modelo-de-teste"


async def test_classificar_envia_schema_estrito_no_output_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ligacao com o SDK e o unico ponto que nenhum dublê alcanca -- fixa a
    forma exata do parametro para que uma regressao apareca aqui, nao so em
    producao.
    """
    resposta = _resposta_json()
    cliente = _ClienteFalso(resposta)
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)

    await ClassificadorAnthropic().classificar(_contexto())

    _, kwargs = cliente.messages.create.call_args
    assert kwargs["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": classificador_mod.SCHEMA_DA_RESPOSTA,
        }
    }
