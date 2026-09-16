import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mobia.domain.context import resumo as resumo_mod
from mobia.domain.context.resumo import ContadorAnthropic, ResumidorAnthropic, ResumoInvalido
from mobia.infra.anthropic import TETO_DO_COUNT_TOKENS, TETO_DO_RESUMO

# Strings que nao podem, sob nenhuma circunstancia, sobreviver ao log. Se um
# destes valores aparecer em `caplog.text`, o boundary vazou conteudo de lead
# ou o prompt que o gerou.
TEXTO_DO_RESUMO = "SENTINELA-RESUMO lead mora na Rua das Palmeiras, quer 2 quartos"
INSTRUCAO_DO_PROMPT = "SENTINELA-PROMPT instrucao confidencial do sistema"
CONTEUDO_DO_PROMPT = "SENTINELA-CONTEUDO mensagens literais do lead"


def _bloco_texto(texto: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=texto)


def _resposta_falsa(
    *,
    texto: str | None,
    stop_reason: str = "end_turn",
    tokens_in: int = 8000,
    tokens_out: int = 500,
) -> SimpleNamespace:
    blocos = [_bloco_texto(texto)] if texto else []
    return SimpleNamespace(
        content=blocos,
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
        stop_reason=stop_reason,
    )


class _ClienteFalso:
    """Dublê minimo do `AsyncAnthropic`: so o que `resumir` toca.

    Nao e um dublê de rede -- e um objeto Python comum que nunca abre socket.
    """

    def __init__(self, resposta: SimpleNamespace) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(return_value=resposta))


def _instalar_cliente_falso(monkeypatch: pytest.MonkeyPatch, resposta: SimpleNamespace) -> None:
    """Troca o `get_client` que `resumo.py` enxerga, nao o global cacheado.

    Como o modulo importa `get_client` por nome (`from ... import get_client`),
    ele guarda a propria referencia -- substituir so essa referencia isola o
    teste do `@lru_cache` de `mobia.infra.anthropic.get_client` e da
    `ANTHROPIC_API_KEY`, sem tocar nenhum dos dois.
    """
    monkeypatch.setattr(resumo_mod, "get_client", lambda: _ClienteFalso(resposta))


async def test_resumir_loga_metricas_sem_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`resumo.gerado` carrega numeros; nunca o texto do resumo nem o prompt."""
    resposta = _resposta_falsa(texto=TEXTO_DO_RESUMO, tokens_in=8000, tokens_out=500)
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO):
        gerado = await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert gerado.texto == TEXTO_DO_RESUMO
    assert gerado.tokens_in == 8000
    assert gerado.tokens_out == 500

    assert "resumo.gerado" in caplog.text
    assert '"tokens_in": 8000' in caplog.text
    assert '"tokens_out": 500' in caplog.text
    assert '"custo_usd"' in caplog.text
    assert '"latency_ms"' in caplog.text
    assert '"modelo"' in caplog.text

    # a parte que importa: nem o resumo nem o prompt que o gerou aparecem.
    assert TEXTO_DO_RESUMO not in caplog.text
    assert INSTRUCAO_DO_PROMPT not in caplog.text
    assert CONTEUDO_DO_PROMPT not in caplog.text


async def test_resumir_recusa_resposta_vazia(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Sem bloco de texto (recusa, bloqueio, so tool_use) nao vira resumo."""
    resposta = _resposta_falsa(texto=None, stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(ResumoInvalido) as erro:
        await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert "vazio" in str(erro.value)
    assert INSTRUCAO_DO_PROMPT not in str(erro.value)
    assert CONTEUDO_DO_PROMPT not in str(erro.value)
    # nada foi gravado como "gerado" -- a chamada nao produziu resumo nenhum.
    assert "resumo.gerado" not in caplog.text


async def test_resumir_recusa_truncamento_por_max_tokens(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Uma resposta cortada no meio da frase nao pode passar por resumo completo."""
    texto_truncado = "o lead quer um apartamento de tres quartos na regiao"
    resposta = _resposta_falsa(texto=texto_truncado, stop_reason="max_tokens")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(ResumoInvalido) as erro:
        await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert "max_tokens" in str(erro.value)
    assert texto_truncado not in str(erro.value)
    assert texto_truncado not in caplog.text
    assert "resumo.gerado" not in caplog.text


async def test_resumir_recusa_texto_so_com_espaco_em_branco(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`not texto` nao pega isto: "   \\n  " e uma string no-vazia de verdade.

    E exatamente o buraco que passava pelo guard anterior (`if not texto`) --
    stop_reason normal, bloco de texto presente, mas sem fato nenhum sobre o
    lead dentro dele.
    """
    resposta = _resposta_falsa(texto="   \n  \t  ", stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    with caplog.at_level(logging.INFO), pytest.raises(ResumoInvalido) as erro:
        await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert "vazio" in str(erro.value)
    assert "resumo.gerado" not in caplog.text


async def test_resumir_remove_espaco_de_borda_do_resumo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Espaco de borda nao pode sobreviver: ele se acumula no prompt do proximo turno.

    Decisao deliberada: `ResumoGerado.texto` guarda o texto apos `.strip()`,
    nao o texto cru da API.
    """
    resposta = _resposta_falsa(texto=f"  \n{TEXTO_DO_RESUMO}\t  ", stop_reason="end_turn")
    _instalar_cliente_falso(monkeypatch, resposta)

    gerado = await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert gerado.texto == TEXTO_DO_RESUMO


async def test_resumir_manda_o_proprio_teto_de_tempo(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEC-228: o resumo e uma das cinco fatias e nao herda o piso do cliente.

    Sem o `timeout=` explicito a chamada cai nos `TIMEOUT_SEGUNDOS = 60.0` da
    construcao -- mais do que o dobro do que esta fatia tem de orcamento, e o
    que fazia a soma do turno estourar o `job_timeout`.
    """
    cliente = _ClienteFalso(_resposta_falsa(texto=TEXTO_DO_RESUMO))
    monkeypatch.setattr(resumo_mod, "get_client", lambda: cliente)

    await ResumidorAnthropic().resumir(INSTRUCAO_DO_PROMPT, CONTEUDO_DO_PROMPT)

    assert cliente.messages.create.call_args.kwargs["timeout"] == TETO_DO_RESUMO


async def test_contar_manda_o_menor_teto_do_turno(monkeypatch: pytest.MonkeyPatch) -> None:
    """`count_tokens` nao gera texto: e ida-e-volta de rede, e o teto reflete isso.

    E a unica fatia cujo teto nao vem de uma geracao medida -- 0,28s de pior
    caso medido contra 5s de teto. A folga em percentual assusta e nao importa:
    o orcamento se paga em segundos, e 5 e menos da metade do menor teto de
    geracao.
    """
    cliente = _ClienteFalso(_resposta_falsa(texto=None))
    cliente.messages = SimpleNamespace(
        count_tokens=AsyncMock(return_value=SimpleNamespace(input_tokens=1234))
    )
    monkeypatch.setattr(resumo_mod, "get_client", lambda: cliente)

    assert await ContadorAnthropic().contar("texto qualquer") == 1234
    assert cliente.messages.count_tokens.call_args.kwargs["timeout"] == TETO_DO_COUNT_TOKENS
