import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.turno import ResultadoDoTurno, executar_turno
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import CLAIMABLE_STATUSES, MessageStatus

log = structlog.get_logger(__name__)

# "skipped" e deste modulo -- claim recusado ou a mensagem sumiu entre o claim
# e a busca -- os outros quatro vem do turno (Task 6, Literal de proposito: ver
# `ResultadoDoTurno`).
ResultadoDoProcessamento = Literal["skipped"] | ResultadoDoTurno


def _detalhe_do_erro(exc: BaseException) -> str:
    """O que pode ser gravado em `messages.last_error` sem risco de vazamento.

    `last_error` e coluna `Text` durvel e **nao** passa pela mascara de PII do
    log. Ate a TEC-134 so excecoes da ingestao chegavam aqui. Agora duas
    chamadas a terceiros ficam a montante -- `contador.contar` e
    `messages.create`, ambas com a conversa decifrada do lead no corpo da
    requisicao -- e `str(exc)` de uma excecao de terceiro nao e uma garantia
    que este projeto possa dar: o SDK em geral nao ecoa o corpo na mensagem,
    mas "em geral" nao e o padrao que a restricao de nao logar conteudo do
    lead aceita.

    Dai o criterio pelo dono do tipo: excecao definida em `mobia` teve a
    mensagem escrita aqui dentro e sabe-se o que ela carrega (ver
    `RespostaInvalida`, que so guarda o nome da classe original). De qualquer
    outra, so o nome -- que ja e o que aponta para o modulo culpado.
    """
    modulo = type(exc).__module__
    if modulo == "mobia" or modulo.startswith("mobia."):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


# Teto proprio para a escrita que registra um cancelamento. Quando ela roda,
# todo prazo ja se foi: o `asyncio.timeout` do arq disparou uma vez e nao volta
# a disparar, e o `wait_for` que o envolvia ja decorreu. Sem teto, um banco
# pendurado -- que e justamente uma das razoes de o turno ter estourado o
# orcamento -- prenderia o slot do worker para sempre e faria o `close()` do
# arq, que espera as tasks de job antes de desligar, nunca retornar.
SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO = 10


async def _marcar_falha(
    session_factory: async_sessionmaker[AsyncSession], identifier: uuid.UUID, detalhe: str
) -> None:
    """Fecha a linha como FAILED e conta a tentativa.

    Nao loga: os dois chamadores emitem eventos diferentes de proposito, e o
    que eles compartilham e so a escrita.
    """
    async with session_factory() as session:
        await session.execute(
            update(Message)
            .where(Message.id == identifier)
            .values(
                status=MessageStatus.FAILED,
                attempts=Message.attempts + 1,
                last_error=detalhe,
            )
        )
        await session.commit()


async def claim_message(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """Reivindica a mensagem para processamento.

    PROCESSING esta entre os estados reivindicaveis de proposito: e o estado que
    um worker morto no meio do job deixa para tras, e e o que permite a retomada.

    A exclusao mutua e **parcial**. O `SELECT ... FOR UPDATE SKIP LOCKED` resolve
    o caso simultaneo: quem chega com a linha travada sai limpo com False, em vez
    de bloquear, reavaliar o predicado contra a nova versao da linha (onde
    PROCESSING continua reivindicavel) e reivindicar tambem. O que ele nao cobre
    e o worker que chega depois do commit do primeiro -- por construcao, ja que
    e assim que a retomada funciona. Exclusao completa pede um lease com coluna
    `claimed_at`, que fica para uma historia posterior.
    """
    reservada = await session.execute(
        select(Message.id)
        .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
        .with_for_update(skip_locked=True)
    )
    if reservada.scalar_one_or_none() is None:
        return False

    # O `execute` de um UPDATE devolve um CursorResult em runtime, mas a tipagem
    # do SQLAlchemy declara o Result generico, que nao expoe `rowcount`.
    resultado = cast(
        CursorResult[Any],
        await session.execute(
            update(Message)
            .where(Message.id == message_id, Message.status.in_(CLAIMABLE_STATUSES))
            .values(status=MessageStatus.PROCESSING)
        ),
    )
    return resultado.rowcount == 1


async def process_message(ctx: dict[str, Any], message_id: str) -> ResultadoDoProcessamento:
    session_factory = ctx["session_factory"]
    outbound = ctx["outbound"]
    identifier = uuid.UUID(message_id)

    async with session_factory() as session:
        if not await claim_message(session, identifier):
            await session.rollback()
            log.info("message.skipped", message_id=message_id, reason="not_claimable")
            return "skipped"
        await session.commit()

    try:
        async with session_factory() as session:
            linha = await session.get(Message, identifier)
        if linha is None:
            log.warning("message.sumiu", message_id=message_id)
            return "skipped"

        resultado = await executar_turno(
            session_factory,
            message=linha,
            classificador=ctx["classificador"],
            resumidor=ctx["resumidor"],
            contador=ctx["contador"],
            outbound=outbound,
        )

        async with session_factory() as session:
            await session.execute(
                update(Message)
                .where(Message.id == identifier)
                .values(status=MessageStatus.PROCESSED, processed_at=datetime.now(UTC))
            )
            await session.commit()
    except Exception as exc:
        detalhe = _detalhe_do_erro(exc)
        await _marcar_falha(session_factory, identifier, detalhe)
        # Mesmo valor da coluna, e pelo mesmo motivo: o log estruturado nao
        # mascara `error`, e a chave nao esta na lista de campos redigidos.
        log.warning("message.failed", message_id=message_id, error=detalhe)
        raise
    except asyncio.CancelledError as exc:
        # `CancelledError` e BaseException, nao Exception: o `except` acima nao
        # a pega. Sem esta clausula a linha fica em PROCESSING -- e como
        # PROCESSING e reivindicavel e `attempts` nao subia, o sweeper
        # reenfileirava para sempre, pagando o turno inteiro a cada volta.
        detalhe = _detalhe_do_erro(exc)
        try:
            async with asyncio.timeout(SEGUNDOS_PARA_REGISTRAR_CANCELAMENTO):
                await _marcar_falha(session_factory, identifier, detalhe)
        except Exception as falha:
            # Esta excecao nao pode escapar: ela **substituiria** o
            # CancelledError, o worker deixaria de ver o cancelamento e o
            # desligamento limpo quebraria -- justamente a garantia que esta
            # clausula existe para dar. Vira evento proprio e o cancelamento
            # segue seu caminho. A linha fica em PROCESSING, que o sweeper
            # ainda recupera, so que sem contar a tentativa.
            log.error(
                "message.cancelled_nao_registrado",
                message_id=message_id,
                reason=type(falha).__name__,
            )
        # Evento proprio, e nao `message.failed`: cancelamento e problema
        # operacional diferente de o turno falhar. Desde a TEC-232 o SIGTERM de
        # um deploy drena os jobs em voo antes de cancelar
        # (`job_completion_wait` em `workers/main.py`), entao o que chega aqui e
        # quase sempre o `job_timeout` estourando. O deploy so alcanca este
        # ponto se o turno atravessar a janela inteira de drenagem -- e ai o
        # orcamento dele realmente acabou. Ver a secao TEC-232 do README.
        log.warning("message.cancelled", message_id=message_id, error=detalhe)
        raise

    log.info("message.processed", message_id=message_id)
    return resultado
