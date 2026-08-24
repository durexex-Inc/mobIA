import uuid
from datetime import UTC, datetime

import structlog
from arq.connections import ArqRedis
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.status import MessageStatus
from mobia.infra.queue import enqueue_process_message

log = structlog.get_logger(__name__)


class IngestionService:
    """Persiste a mensagem recebida e so entao a enfileira.

    A ordem importa: a linha commitada no Postgres e a garantia de nao-perda.
    Depois do `_persist` nada propaga: tanto o enqueue quanto a virada de status
    sao otimistas e engolem as proprias falhas -- a mensagem fica em RECEIVED e o
    sweeper (workers/jobs/sweep_stalled.py) a recupera.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: ArqRedis | None,
    ) -> None:
        self._session_factory = session_factory
        self._queue = queue

    async def ingest(
        self, parsed: list[ParsedMessage], channel: str = "whatsapp"
    ) -> list[uuid.UUID]:
        if not parsed:
            return []

        message_ids = await self._persist(parsed, channel)
        for message_id in message_ids:
            await self._try_enqueue(message_id)
        return message_ids

    async def _persist(self, parsed: list[ParsedMessage], channel: str) -> list[uuid.UUID]:
        """Grava as mensagens novas e descarta as que a Meta ja tinha entregue.

        O descarte e resolvido pelo `ON CONFLICT` do proprio Postgres, nao por
        uma checagem em memoria: duas replicas da API recebendo a mesma reentrega
        ao mesmo tempo so podem ser separadas pela constraint (TEC-125). O
        `DO NOTHING` tambem impede que uma duplicata no meio do lote derrube as
        mensagens legitimas que vieram junto.
        """
        valores = [
            {
                "id": uuid.uuid4(),
                "channel": channel,
                "provider_message_id": item.provider_message_id,
                "sender_external_id": item.sender_external_id,
                "recipient_external_id": item.recipient_external_id,
                "content_type": item.content_type,
                "text_body": item.text_body,
                "raw_payload": item.raw_payload,
                "status": MessageStatus.RECEIVED,
            }
            for item in parsed
        ]
        statement = (
            pg_insert(Message)
            .values(valores)
            .on_conflict_do_nothing(constraint="uq_messages_channel_provider_message_id")
            .returning(Message.id, Message.provider_message_id)
        )

        async with self._session_factory() as session:
            resultado = await session.execute(statement)
            inseridas = resultado.all()
            await session.commit()

        gravados = {linha.provider_message_id for linha in inseridas}
        for item in parsed:
            if item.provider_message_id not in gravados:
                log.info(
                    "message.duplicate_discarded",
                    provider_message_id=item.provider_message_id,
                    channel=channel,
                )

        message_ids = [linha.id for linha in inseridas]
        if message_ids:
            log.info(
                "message.received",
                message_ids=[str(i) for i in message_ids],
                channel=channel,
            )
        return message_ids

    async def _try_enqueue(self, message_id: uuid.UUID) -> None:
        if self._queue is None:
            log.warning("enqueue.failed", message_id=str(message_id), reason="no_queue")
            return
        try:
            await enqueue_process_message(self._queue, message_id)
        except Exception as exc:
            log.warning(
                "enqueue.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        # O predicado de status importa: entre o enqueue voltar e este commit
        # aterrissar, um worker pode ter reivindicado e concluido a mensagem.
        # Sem ele, o webhook atropelaria PROCESSED de volta para QUEUED.
        #
        # A falha aqui tambem e engolida, e por um motivo mais forte que a do
        # enqueue: neste ponto o `_persist` ja commitou as linhas. Deixar subir
        # viraria 500 na rota e a Meta re-entregaria um payload cujas linhas ja
        # existem; como provider_message_id so vira UNIQUE em TEC-125, a
        # re-entrega nasceria como segunda linha, com message_id diferente --
        # que a guarda UNIQUE (message_id, kind) de outbound_dispatches nao casa,
        # e o lead levaria duas respostas. A linha fica em RECEIVED e o sweeper
        # a recupera sem precisar de nada da Meta.
        try:
            async with self._session_factory() as session:
                resultado = await session.execute(
                    update(Message)
                    .where(Message.id == message_id, Message.status == MessageStatus.RECEIVED)
                    .values(status=MessageStatus.QUEUED, queued_at=datetime.now(UTC))
                )
                await session.commit()
        except Exception as exc:
            log.warning(
                "queued_flag.failed",
                message_id=str(message_id),
                reason=type(exc).__name__,
                detail=str(exc),
            )
            return

        if resultado.rowcount == 1:
            log.info("message.queued", message_id=str(message_id))
        else:
            log.info(
                "message.queued_skipped",
                message_id=str(message_id),
                reason="status_ja_avancou",
            )
