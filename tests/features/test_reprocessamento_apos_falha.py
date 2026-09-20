"""Cenario Gherkin de TEC-122: nao perder mensagem em falha do worker."""

import asyncio
import uuid
from typing import Any

import pytest
from conftest import (
    ClassificadorFake,
    ContadorFake,
    ModeradorFake,
    ResumidorFake,
    eventos_de_log,
)
from sqlalchemy import func, select

from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.models import OutboundDispatch
from mobia.domain.outbound.port import GuardedOutbound
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import claim_message, process_message


def _ctx(session_factory, outbound) -> dict[str, Any]:
    """Monta o ctx completo que `process_message` agora exige.

    Desde a TEC-134 `process_message` roda o turno inteiro, entao alem de
    `session_factory`/`outbound` ele precisa das cinco portas do agente -- este
    modulo testa reprocessamento e reserva de outbound, nao classificacao, dai
    os dubles fixos em vez das fixtures parametrizaveis de `test_turno.py`.
    `agendador` entrou na TEC-175: `process_message` le `ctx["agendador"]`
    direto, sem fallback -- ver o comentario em `process_message.py` sobre por
    que um `ctx.get(...) or AgendadorNoop()` esconderia em silencio um
    `startup` que deixasse de popular a chave.
    """
    return {
        "session_factory": session_factory,
        "outbound": outbound,
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "indicador": IndicadorNoop(),
    }


class OutboundEspiao(GuardedOutbound):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.entregas: list[uuid.UUID] = []

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        self.entregas.append(message_id)


class QuedaDoWorker(RuntimeError):
    pass


class OutboundQueCai(OutboundEspiao):
    """Registra a entrega e so entao levanta.

    Reproduz a janela que o cenario 3 precisa exercitar: o efeito externo ja
    saiu, mas a linha ainda nao chegou a PROCESSED.
    """

    async def _deliver(self, message_id: uuid.UUID, kind: str, payload: dict[str, Any]) -> None:
        await super()._deliver(message_id, kind, payload)
        raise QuedaDoWorker("worker morto no meio do processamento")


async def enfileirada(session, status: str = MessageStatus.QUEUED) -> uuid.UUID:
    identificador = uuid.uuid4()
    message = Message(
        id=identificador,
        channel="whatsapp",
        provider_message_id=f"wamid.{uuid.uuid4().hex[:8]}",
        sender_external_id="5511911112222",
        recipient_external_id="222222222",
        conversation_key="5511911112222",
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=encrypt("ainda tem o 2 quartos?", aad_de(identificador, "text_body")),
        raw_payload=None,
        status=status,
    )
    session.add(message)
    await session.commit()
    return message.id


async def test_processa_mensagem_enfileirada(session) -> None:
    message_id = await enfileirada(session)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = _ctx(get_sessionmaker(), outbound)

    assert await process_message(ctx, str(message_id)) == "respondido"

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert linha.processed_at is not None
    assert outbound.entregas == [message_id]


async def test_mensagem_ja_processada_e_ignorada(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = _ctx(get_sessionmaker(), outbound)

    assert await process_message(ctx, str(message_id)) == "skipped"
    assert outbound.entregas == []


async def test_claim_recusa_status_terminal(session) -> None:
    message_id = await enfileirada(session, status=MessageStatus.PROCESSED)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is False


async def test_claim_aceita_processing_para_permitir_retomada(session) -> None:
    """PROCESSING e o estado que um worker morto deixa; tem de ser reivindicavel."""
    message_id = await enfileirada(session, status=MessageStatus.PROCESSING)
    async with get_sessionmaker()() as sessao:
        assert await claim_message(sessao, message_id) is True
        await sessao.commit()


async def test_claim_simultaneo_faz_o_segundo_worker_perder_limpo(session) -> None:
    """Dois workers na mesma mensagem ao mesmo tempo.

    Sem o SELECT ... FOR UPDATE SKIP LOCKED o segundo bloqueava no lock do
    primeiro, reavaliava o predicado contra a linha ja em PROCESSING -- que
    continua reivindicavel -- e reivindicava tambem, dobrando o trabalho.
    """
    message_id = await enfileirada(session)
    session_factory = get_sessionmaker()

    async with session_factory() as primeiro, session_factory() as segundo:
        # O primeiro nao commita: mantem o lock da linha, como um job em curso.
        assert await claim_message(primeiro, message_id) is True
        perdedor = await asyncio.wait_for(claim_message(segundo, message_id), timeout=5)
        assert perdedor is False, "o segundo worker tem de sair como no-op"
        await primeiro.commit()


async def test_nao_perder_mensagem_em_falha_do_worker(session) -> None:
    """Cenario: Nao perder mensagem em falha do worker.

    Dada uma mensagem ja enfileirada e um worker interrompido durante o
    processamento, quando o worker e reiniciado, a mensagem volta a ser
    processada e nenhuma resposta duplicada e enviada ao lead.

    A janela que `OutboundQueCai` reproduz -- entrega externa ja feita,
    reserva ja commitada, processo morto antes de gravar a fala -- e a mesma
    que TEC-134 fechou depois de um round de review: sem checar o retorno de
    `send()`, o reprocessamento caia na guarda de reentrega (Task 3), que
    devolve False sem levantar, e gravava a fala da *segunda* chamada ao
    classificador como se fosse o que o lead recebeu na primeira -- fala
    fantasma pela porta que a ordem grava-depois-de-entregar nao cobre. Este
    teste e o motivo pelo qual esse bug so foi pego numa review: ele so
    checava nivel de dispatch, nunca a contagem de linhas OUTBOUND.
    """
    message_id = await enfileirada(session)

    # Worker interrompido logo depois da entrega, antes de marcar PROCESSED.
    caido = OutboundQueCai(get_sessionmaker())
    ctx = _ctx(get_sessionmaker(), caido)
    with pytest.raises(QuedaDoWorker):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.attempts == 1
    assert len(caido.entregas) == 1

    # Worker reiniciado: instancia nova, sem a falha. A reserva da primeira
    # tentativa persiste (so EnvioRetentavel libera, e QuedaDoWorker nao e
    # isso), entao esta chamada colide na guarda e nunca chega a `_deliver`.
    reiniciado = OutboundEspiao(get_sessionmaker())
    ctx["outbound"] = reiniciado
    assert await process_message(ctx, str(message_id)) == "reentrega_suprimida"

    await session.refresh(linha)
    assert linha.status == MessageStatus.PROCESSED
    assert reiniciado.entregas == [], "a guarda suprime a reentrega"
    assert await session.scalar(select(func.count()).select_from(OutboundDispatch)) == 1

    # O texto que de fato saiu na primeira tentativa (`caido.entregas`) nunca
    # chega a existir como linha em `messages` -- o processo morreu antes de
    # gravar. A segunda tentativa nao pode inventar essa linha com o texto de
    # uma chamada nova ao classificador: 0, nao 1, e a contagem correta aqui.
    # Ver `test_reentrega_suprimida_nao_grava_fala_fantasma` em
    # `test_turno.py` para o caso isolado, sem a camada de reprocessamento.
    total_outbound = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.direction == MessageDirection.OUTBOUND)
    )
    assert total_outbound == 0, "nenhuma fala fantasma -- a de verdade se perdeu no crash"


async def test_mensagem_em_received_tambem_e_processavel(session) -> None:
    """Cobre a linha que o sweeper recupera: nunca chegou a ficar QUEUED."""
    message_id = await enfileirada(session, status=MessageStatus.RECEIVED)
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = _ctx(get_sessionmaker(), outbound)

    assert await process_message(ctx, str(message_id)) == "respondido"
    assert outbound.entregas == [message_id]


async def test_mensagem_inexistente_e_ignorada() -> None:
    outbound = OutboundEspiao(get_sessionmaker())
    ctx = _ctx(get_sessionmaker(), outbound)
    assert await process_message(ctx, str(uuid.uuid4())) == "skipped"


class ErroDeTerceiro(RuntimeError):
    """Fica fora do pacote `mobia` de proposito -- e o ponto do teste.

    Reproduz uma excecao de SDK: `contador.contar` e `messages.create` mandam
    a conversa decifrada do lead no corpo da requisicao, e nada garante o que
    a biblioteca decide colocar em `str(exc)`.
    """


SENTINELA = "SENTINELA lead mora na Rua das Palmeiras e quer 2 quartos"


async def test_erro_de_terceiro_nao_leva_a_mensagem_para_last_error(session, caplog) -> None:
    """`messages.last_error` e coluna durvel e nao passa pela mascara de PII.

    Ate a TEC-134 so excecao da ingestao chegava ali. Agora duas chamadas a
    terceiros ficam a montante, com a conversa do lead no corpo da requisicao.
    So o nome da classe pode atravessar essa fronteira.
    """
    message_id = await enfileirada(session)
    ctx = _ctx(get_sessionmaker(), OutboundEspiao(get_sessionmaker()))
    ctx["classificador"] = ClassificadorFake(erro=ErroDeTerceiro(SENTINELA))

    with caplog.at_level("INFO"), pytest.raises(ErroDeTerceiro):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.last_error == "ErroDeTerceiro"
    assert SENTINELA not in (linha.last_error or "")
    assert SENTINELA not in caplog.text


async def test_erro_do_proprio_projeto_tambem_so_deixa_o_nome_na_coluna(session, caplog) -> None:
    """Ate a TEC-222 este teste afirmava o contrario, e a premissa dele caiu.

    O docstring antigo dizia: "excecao de `mobia` teve a mensagem escrita aqui
    dentro -- sabe-se o que ela carrega". Nao se sabe.
    `ModeracaoIndisponivel` desmente a frase, e o teste ao lado prova. Como a
    garantia nao pode depender de cada autor futuro de excecao, a coluna deixou
    de guardar texto de qualquer origem -- inclusive quando ele e, de fato,
    inofensivo, como aqui.

    O diagnostico nao se perde: o log de `message.failed` continua com o texto.
    """
    from mobia.domain.agente.classificador import RespostaInvalida

    message_id = await enfileirada(session)
    ctx = _ctx(get_sessionmaker(), OutboundEspiao(get_sessionmaker()))
    ctx["classificador"] = ClassificadorFake(erro=RespostaInvalida("JSONDecodeError"))

    with caplog.at_level("INFO"), pytest.raises(RespostaInvalida):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.last_error == "RespostaInvalida"

    ((_, corpo),) = eventos_de_log(caplog, "message.failed")
    assert corpo["error"] == "RespostaInvalida: JSONDecodeError"


# Prosa que o SERVIDOR da Anthropic escreve, nao texto que este projeto montou.
# `motivo_do_provedor` (infra/anthropic.py) devolve ate 300 caracteres dela, e
# `ModeracaoIndisponivel` a carrega ate `last_error` -- ver o desenho da
# TEC-222. O valor aqui imita um 400 de validacao que cite o payload recusado.
MOTIVO_DO_PROVEDOR = "400 invalid_request: 'quero 2 quartos'"


async def test_texto_de_provedor_em_excecao_do_projeto_nao_chega_a_coluna(session, caplog) -> None:
    """A excecao e de `mobia`, mas a mensagem dela nao foi escrita aqui dentro.

    `ModeracaoIndisponivel` vem de `domain/moderacao/port.py`, entao o criterio
    da TEC-134 -- dono do tipo -- deixava o texto inteiro entrar na coluna. Mas
    `infra/moderacao.py` a levanta com `motivo_do_provedor(exc)`, que e o corpo
    de erro do servidor da Anthropic, em resposta a uma requisicao cujo corpo e
    o texto moderado. Dono do tipo nao e dono da mensagem.

    A moderacao de SAIDA nao falha aberta de proposito (ver `turno.py`), entao
    a excecao propaga ate `process_message` e chega a coluna.
    """
    from mobia.domain.moderacao.port import ModeracaoIndisponivel

    message_id = await enfileirada(session)
    ctx = _ctx(get_sessionmaker(), OutboundEspiao(get_sessionmaker()))
    ctx["moderador"] = ModeradorFake(erro_na_saida=ModeracaoIndisponivel(MOTIVO_DO_PROVEDOR))

    with caplog.at_level("INFO"), pytest.raises(ModeracaoIndisponivel):
        await process_message(ctx, str(message_id))

    linha = await session.get(Message, message_id)
    await session.refresh(linha)
    assert linha.status == MessageStatus.FAILED
    assert linha.last_error == "ModeracaoIndisponivel"
    assert MOTIVO_DO_PROVEDOR not in (linha.last_error or "")

    # A outra metade da divisao do desenho, e ela precisa ser afirmada: uma
    # implementacao que emudecesse o log junto passaria na asserta de cima e
    # seria regressao de diagnostico. O log MANTEM o texto, pela regra da
    # TEC-134, onde o raciocinio da TEC-237 se aplica ao destino para o qual
    # foi escrito.
    ((_, corpo),) = eventos_de_log(caplog, "message.failed")
    assert corpo["error"] == f"ModeracaoIndisponivel: {MOTIVO_DO_PROVEDOR}"
