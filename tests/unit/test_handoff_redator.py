import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mobia.domain.handoff import resumo as resumo_mod
from mobia.domain.handoff.resumo import (
    LIMITE_DE_CARACTERES,
    MARCADORES,
    RedatorAnthropic,
    ResumoDeHandoffInvalido,
)

# Se qualquer uma destas aparecer em caplog.text, o boundary vazou conteudo
# de lead ou o dossie que o gerou. Mesmo molde de tests/unit/test_resumo.py.
SENTINELA_DOSSIE = "SENTINELA-DOSSIE lead mora na Rua das Palmeiras"
SENTINELA_SAIDA = "SENTINELA-SAIDA o lead quer 2 quartos em Pinheiros"


def _resumo(recheio: str = "curto") -> str:
    return "\n".join(f"{marcador}\n{recheio}" for marcador in MARCADORES)


def _resposta(texto: str | None, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)] if texto else [],
        usage=SimpleNamespace(input_tokens=900, output_tokens=400),
        stop_reason=stop_reason,
    )


class _ClienteFalso:
    """Duble minimo do AsyncAnthropic: so o que `redigir` toca."""

    def __init__(self, *respostas: SimpleNamespace) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(side_effect=list(respostas)))


def _instalar(monkeypatch: pytest.MonkeyPatch, *respostas: SimpleNamespace) -> _ClienteFalso:
    cliente = _ClienteFalso(*respostas)
    monkeypatch.setattr(resumo_mod, "get_client", lambda: cliente)
    return cliente


async def test_redigir_devolve_o_resumo_validado(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta(_resumo()))

    gerado = await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    assert MARCADORES[0] in gerado.texto
    assert gerado.comprimiu is False
    assert gerado.tokens_in == 900


async def test_estouro_do_limite_tenta_comprimir_uma_vez(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    longo = _resumo("x" * LIMITE_DE_CARACTERES)
    cliente = _instalar(monkeypatch, _resposta(longo), _resposta(_resumo()))

    gerado = await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    assert gerado.comprimiu is True
    assert cliente.messages.create.await_count == 2


async def test_estouro_na_compressao_levanta_em_vez_de_truncar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    longo = _resumo("x" * LIMITE_DE_CARACTERES)
    cliente = _instalar(monkeypatch, _resposta(longo), _resposta(longo))

    with pytest.raises(ResumoDeHandoffInvalido, match="acima do limite"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    # Uma tentativa de compressao, nao um laco: duas chamadas ja estouram o
    # orcamento de 8s da RNF-05 no caso ruim.
    assert cliente.messages.create.await_count == 2


async def test_bloco_faltando_nao_e_recuperado_por_compressao(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manco = "\n".join(f"{m}\ntexto" for m in MARCADORES[:-1])
    cliente = _instalar(monkeypatch, _resposta(manco))

    with pytest.raises(ResumoDeHandoffInvalido, match="bloco ausente"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    # Comprimir um resumo que ja perdeu um bloco nao o traz de volta.
    assert cliente.messages.create.await_count == 1


async def test_parada_anormal_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    _instalar(monkeypatch, _resposta(_resumo(), stop_reason="max_tokens"))

    with pytest.raises(ResumoDeHandoffInvalido, match="stop_reason"):
        await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")


async def test_log_carrega_metrica_e_nunca_conteudo(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _instalar(monkeypatch, _resposta(_resumo(SENTINELA_SAIDA)))

    with caplog.at_level(logging.INFO):
        await RedatorAnthropic().redigir(SENTINELA_DOSSIE)

    assert "resumo_handoff.gerado" in caplog.text
    assert SENTINELA_DOSSIE not in caplog.text
    assert SENTINELA_SAIDA not in caplog.text


async def test_o_resumo_de_handoff_nao_manda_teto_proprio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fica no piso de construcao do cliente, e isso e deliberado (TEC-228).

    A TEC-228 deu teto proprio as cinco fatias do TURNO porque elas dividem um
    `job_timeout` de 240s. Esta nao e uma delas: roda no job `gerar_resumo`,
    sozinha, e ninguem mediu quanto ela leva -- o dossie e entrada bem maior
    que a de `context/resumo.py`. Inventar um numero de aparencia medida para
    ela seria o palpite que aquela card existe para acabar.

    O teste afirma a AUSENCIA porque a ausencia e a decisao. Um `timeout=` que
    aparecesse aqui sem medicao passaria despercebido em revisao.
    """
    cliente = _instalar(monkeypatch, _resposta(_resumo()))

    await RedatorAnthropic().redigir("ORIGEM\ncanal: whatsapp")

    assert "timeout" not in cliente.messages.create.call_args.kwargs
