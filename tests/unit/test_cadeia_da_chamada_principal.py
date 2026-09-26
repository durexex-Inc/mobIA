"""A cadeia da chamada principal: retentativa, secundario e prazo. TEC-209, D2.

Sem rede e sem banco: o cliente Anthropic e um dublê que devolve, chamada a
chamada, o que o teste mandar -- uma resposta ou uma excecao do SDK --, e
guarda o modelo que cada requisicao pediu. A espera entre tentativas e
trocada por uma que so registra, para o teste nao dormir.
"""

import json
import time
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import pytest

from mobia.app.config import get_settings
from mobia.domain.agente import classificador as classificador_mod
from mobia.domain.agente.classificador import (
    ClassificadorAnthropic,
    ProvedorIndisponivel,
    RespostaInvalida,
)
from mobia.domain.context.montagem import ContextoMontado, PrazoDaResposta

_REQUISICAO = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _sobrecarga() -> anthropic.InternalServerError:
    return anthropic.InternalServerError(
        "overloaded", response=httpx.Response(529, request=_REQUISICAO), body=None
    )


def _saldo_esgotado() -> anthropic.BadRequestError:
    return anthropic.BadRequestError(
        "credit balance too low", response=httpx.Response(400, request=_REQUISICAO), body=None
    )


def _resposta() -> SimpleNamespace:
    texto = json.dumps({"intencao": "COMPRA", "confianca": 0.9, "resposta": "Oi!"})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=texto)],
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        ),
        stop_reason="end_turn",
    )


class _Cliente:
    """Devolve os desfechos em ordem e guarda o modelo de cada requisicao."""

    def __init__(self, *desfechos: Any) -> None:
        self._desfechos = list(desfechos)
        self.modelos: list[str] = []
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs: Any) -> Any:
        self.modelos.append(kwargs["model"])
        desfecho = self._desfechos.pop(0)
        if isinstance(desfecho, BaseException):
            raise desfecho
        return desfecho


@pytest.fixture
def esperas(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    registradas: list[float] = []

    async def _registrar(segundos: float) -> None:
        registradas.append(segundos)

    monkeypatch.setattr(classificador_mod, "_esperar", _registrar)
    return registradas


def _instalar(monkeypatch: pytest.MonkeyPatch, cliente: _Cliente) -> None:
    monkeypatch.setattr(classificador_mod, "get_client", lambda: cliente)


def _contexto(prazo: PrazoDaResposta | None = None) -> ContextoMontado:
    return ContextoMontado(
        sistema="s",
        resumo=None,
        literais=[],
        estado=None,
        tokens=10,
        degradado=False,
        prazo_da_resposta=prazo or PrazoDaResposta(),
    )


async def test_o_primario_que_responde_nao_retenta(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    cliente = _Cliente(_resposta())
    _instalar(monkeypatch, cliente)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    assert cliente.modelos == [get_settings().modelo_agente]
    assert esperas == []
    assert resultado.modelo == get_settings().modelo_agente


async def test_duas_falhas_e_a_terceira_tentativa_responde(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    """RNF-27: duas novas tentativas, com espera de 1 s e depois de 2 s."""
    cliente = _Cliente(_sobrecarga(), anthropic.APITimeoutError(_REQUISICAO), _resposta())
    _instalar(monkeypatch, cliente)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    primario = get_settings().modelo_agente
    assert cliente.modelos == [primario, primario, primario]
    assert esperas == [1.0, 2.0]
    assert resultado.modelo == primario


async def test_o_primario_esgotado_passa_ao_secundario(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    """O primeiro cenario da card, e o modelo registrado e o que respondeu."""
    cliente = _Cliente(_sobrecarga(), _sobrecarga(), _sobrecarga(), _resposta())
    _instalar(monkeypatch, cliente)

    resultado = await ClassificadorAnthropic().classificar(_contexto())

    settings = get_settings()
    assert cliente.modelos == [settings.modelo_agente] * 3 + [settings.modelo_agente_secundario]
    assert resultado.modelo == settings.modelo_agente_secundario


async def test_os_dois_esgotados_levantam_provedor_indisponivel(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    cliente = _Cliente(*[_sobrecarga() for _ in range(4)])
    _instalar(monkeypatch, cliente)

    with pytest.raises(ProvedorIndisponivel):
        await ClassificadorAnthropic().classificar(_contexto())

    assert len(cliente.modelos) == 4


async def test_erro_que_nao_e_de_disponibilidade_sobe_na_primeira(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    """Um 400 se repetiria igual: nem retenta nem troca de modelo."""
    cliente = _Cliente(_saldo_esgotado(), _resposta())
    _instalar(monkeypatch, cliente)

    with pytest.raises(anthropic.BadRequestError):
        await ClassificadorAnthropic().classificar(_contexto())

    assert len(cliente.modelos) == 1


async def test_resposta_fora_do_schema_nao_retenta(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    vazia = _resposta()
    vazia.content = []
    cliente = _Cliente(vazia, _resposta())
    _instalar(monkeypatch, cliente)

    with pytest.raises(RespostaInvalida):
        await ClassificadorAnthropic().classificar(_contexto())

    assert len(cliente.modelos) == 1


async def test_prazo_esgotado_nao_tenta_mais(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    """D2: o prazo e do turno. Sem tempo, a cadeia desiste antes de chamar."""
    cliente = _Cliente(_resposta())
    _instalar(monkeypatch, cliente)

    with pytest.raises(ProvedorIndisponivel):
        await ClassificadorAnthropic().classificar(_contexto(PrazoDaResposta(segundos=0.0)))

    assert cliente.modelos == []


async def test_a_virada_do_investidor_herda_o_prazo_que_a_chamada_1_gastou(
    monkeypatch: pytest.MonkeyPatch, esperas: list[float]
) -> None:
    """D2: as duas fatias dividem UM prazo, que mora no contexto do turno.

    A chamada 1 responde; o relogio e entao levado ao fim, como se ela o
    tivesse gasto inteiro. A virada, com o mesmo contexto, desiste sem chamar
    o provedor -- com um prazo por chamada, ela teria 110 s novos.
    """
    contexto = _contexto()
    cliente = _Cliente(_resposta())
    _instalar(monkeypatch, cliente)
    await ClassificadorAnthropic().classificar(contexto)
    contexto.prazo_da_resposta._fim = time.monotonic()

    with pytest.raises(ProvedorIndisponivel):
        await ClassificadorAnthropic().qualificar_investidor(contexto)

    assert len(cliente.modelos) == 1
