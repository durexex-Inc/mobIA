"""TEC-227: o cancelamento do `job_timeout` nao pode sumir com a mensagem.

`asyncio.CancelledError` e `BaseException`, nao `Exception`. Todo teste aqui
forca um cancelamento **de verdade** -- `tarefa.cancel()` numa task em voo --
porque essa e a diferenca que constitui o defeito: um teste que levantasse uma
excecao comum passaria com o bug intacto.
"""

import asyncio
import logging
from typing import Any

import pytest
from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake, _entrada_do_lead
from sqlalchemy import func, select

from mobia.domain.agendamento.agendador import AgendadorDeAvisosNoop
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[Any] = []

    async def _deliver(self, message_id, kind, payload) -> None:
        self.entregas.append(message_id)


class ClassificadorQueTrava(ClassificadorFake):
    """Entra na classificacao e nunca sai.

    E o ponto onde o cancelamento cai nos testes que so precisam de um turno
    interrompido -- antes de qualquer reserva de envio.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entrou = asyncio.Event()

    async def classificar(self, contexto, *, porta=None):
        # TEC-265 adicionou porta= ao chamador. Uma override que nao o aceita
        # levanta TypeError antes de entrou.set(), transformando cada teste
        # neste arquivo numa travesia em vez de uma falha diagnosticavel.
        self.entrou.set()
        await asyncio.Event().wait()
        raise AssertionError("inalcancavel")


def _ctx(outbound, classificador=None) -> dict[str, Any]:
    return {
        "session_factory": get_sessionmaker(),
        "outbound": outbound,
        "classificador": classificador or ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_avisos": AgendadorDeAvisosNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }


async def test_cancelamento_deixa_a_mensagem_em_failed(session) -> None:
    """Hoje a linha fica em PROCESSING para sempre, invisivel.

    O `except Exception` de `process_message` nao pega BaseException, entao
    nada marca a linha e `attempts` nunca sobe -- o turno some do estado da
    mensagem sem deixar rastro.
    """
    linha = await _entrada_do_lead(session)
    travado = ClassificadorQueTrava()

    tarefa = asyncio.create_task(
        process_message(_ctx(OutboundEspiao(get_sessionmaker()), travado), str(linha.id))
    )
    await travado.entrou.wait()
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    gravada = await session.get(Message, linha.id)
    await session.refresh(gravada)
    assert gravada.status == MessageStatus.FAILED
    assert gravada.attempts == 1


async def test_cancelamento_registra_last_error_e_loga(session, caplog) -> None:
    """Sem isso, FAILED nao diz *por que* -- e cancelamento nao e falha comum.

    `attempts` subindo sem motivo registrado faz o turno parecer um erro de
    processamento qualquer, quando o que aconteceu foi o orcamento de tempo do
    worker estourar. Sao problemas operacionais diferentes e o evento proprio
    e o que permite alertar so num deles.
    """
    linha = await _entrada_do_lead(session)
    travado = ClassificadorQueTrava()

    with caplog.at_level(logging.WARNING):
        tarefa = asyncio.create_task(
            process_message(_ctx(OutboundEspiao(get_sessionmaker()), travado), str(linha.id))
        )
        await travado.entrou.wait()
        tarefa.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tarefa

    gravada = await session.get(Message, linha.id)
    await session.refresh(gravada)
    assert gravada.last_error == "CancelledError"
    assert "message.cancelled" in caplog.text
    assert "message.failed" not in caplog.text, "os dois eventos tem de ser distinguiveis"


class OutboundQueTrava(GuardedOutbound):
    """Reserva, entra no `_deliver` e nunca sai.

    Reproduz a janela cara: a reserva ja esta commitada quando o cancelamento
    cai. E a companheira de `test_reserva_liberada.py`, que cobre as
    liberacoes por excecao tipada -- aqui o gatilho e BaseException.
    """

    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entrou = asyncio.Event()

    async def _deliver(self, message_id, kind, payload) -> None:
        self.entrou.set()
        await asyncio.Event().wait()


async def test_cancelamento_durante_a_entrega_libera_a_reserva(session) -> None:
    """Manter a reserva aqui e a perda silenciosa que o card existe para fechar.

    Com ela commitada, o sweeper reenfileira, a guarda responde "ja entreguei
    isso", o turno fecha em PROCESSED terminal e o lead nunca recebe nada. A
    TEC-134 ja tinha escolhido o mesmo lado para `EnvioRetentavel`: entre
    receber duas vezes e nunca receber, a duplicata ganha.
    """
    linha = await _entrada_do_lead(session)
    travado = OutboundQueTrava(get_sessionmaker())

    tarefa = asyncio.create_task(travado.send(linha.id, "reply", {"texto": "oi"}))
    await travado.entrou.wait()
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    reservas = await session.scalar(select(func.count()).select_from(OutboundDispatch))
    assert reservas == 0, "a proxima tentativa precisa poder entregar"


async def test_apos_o_cancelamento_a_retentativa_entrega(session) -> None:
    """O criterio de aceite do card, ponta a ponta.

    Cancelamento depois da reserva commitada nao pode deixar a mensagem
    terminal sem resposta.

    O que este teste sozinho pin e a **liberacao da reserva**: sem ela a
    retentativa colide na guarda, vira `reentrega_suprimida` e fecha em
    PROCESSED com o lead sem nada. Ele nao pin o FAILED -- PROCESSING tambem
    esta em CLAIMABLE_STATUSES, entao a retentativa reivindicaria a linha do
    mesmo jeito. Quem prova a outra metade sao os dois primeiros testes deste
    arquivo.
    """
    linha = await _entrada_do_lead(session)
    travado = OutboundQueTrava(get_sessionmaker())

    tarefa = asyncio.create_task(process_message(_ctx(travado), str(linha.id)))
    await travado.entrou.wait()
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa

    reiniciado = OutboundEspiao(get_sessionmaker())
    assert await process_message(_ctx(reiniciado), str(linha.id)) == "respondido"
    assert reiniciado.entregas == [linha.id], "o lead recebe na retentativa"

    gravada = await session.get(Message, linha.id)
    await session.refresh(gravada)
    assert gravada.status == MessageStatus.PROCESSED


class FabricaQueFalhaDepois:
    """Delega para a fabrica real ate a n-esima chamada, e entao levanta.

    Serve para colocar a falha exatamente na sessao que o handler de
    cancelamento abre -- que e o momento em que o banco tem mais chance de
    estar fora do ar, ja que um banco pendurado e uma das razoes de o turno
    ter estourado o orcamento.
    """

    def __init__(self, falhar_na: int) -> None:
        self._real = get_sessionmaker()
        self._falhar_na = falhar_na
        self.chamadas = 0

    def __call__(self):
        self.chamadas += 1
        if self.chamadas == self._falhar_na:
            raise OSError("conexao com o banco caiu")
        return self._real()


async def test_falha_ao_registrar_o_cancelamento_nao_engole_o_cancelamento(session, caplog) -> None:
    """A garantia "continua propagando" nao pode depender de o banco responder.

    Se a escrita do FAILED levantar, essa excecao **substitui** o
    CancelledError: o worker deixa de ver o cancelamento, o desligamento limpo
    quebra, e a linha fica em PROCESSING sem nada no log dizendo por que.
    """
    linha = await _entrada_do_lead(session)
    travado = ClassificadorQueTrava()
    # Nunca falhar de saida: a primeira sessao e a do claim, e derruba-la
    # mataria a task antes de o classificador ser alcancado.
    fabrica = FabricaQueFalhaDepois(falhar_na=0)

    ctx = _ctx(OutboundEspiao(get_sessionmaker()), travado)
    ctx["session_factory"] = fabrica

    tarefa = asyncio.create_task(process_message(ctx, str(linha.id)))
    await travado.entrou.wait()
    fabrica._falhar_na = fabrica.chamadas + 1
    tarefa.cancel()
    with caplog.at_level(logging.ERROR):
        with pytest.raises(asyncio.CancelledError):
            await tarefa

    assert "message.cancelled_nao_registrado" in caplog.text
