"""A dead-letter queue de mensagens. TEC-209, D5, RNF-33.

Duas rotas, as duas com `OPERAR_FILA` (so ADMIN): listar as mensagens cujas
tentativas esgotaram, e devolver uma delas ao pipeline.

**A lista nao traz conteudo nem `conversation_key`.** No WhatsApp a chave e o
telefone, e a fala e dado pessoal: o operador decide pelo erro e pelo
instante, e quem precisa da conversa abre o lead pelo caminho auditado
(TEC-193). O `id` basta para reprocessar.

**A "fila" e a propria tabela `messages`.** A linha ja guarda tudo o que o
reprocessamento precisa, e uma copia numa segunda estrutura poderia divergir
dela -- a mensagem reprocessada numa, ainda "morta" na outra.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, and_, or_, select, update

from mobia.api.autorizacao import Exige, IdentidadeDaRequisicao
from mobia.app.config import get_settings
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.usuarios.permissoes import Permissao
from mobia.infra.db import get_sessionmaker
from mobia.infra.queue import enqueue_process_message

router = APIRouter(prefix="/api/v1/mensagens", tags=["mensagens"])

_OPERADOR = Depends(Exige(Permissao.OPERAR_FILA))


def _esgotada() -> ColumnElement[bool]:
    """ESGOTADA, ou FAILED que ja esgotou antes de ESGOTADA existir.

    A `0061` nao reclassificou as linhas antigas: elas continuam FAILED com
    `attempts >= sweep_max_attempts`, e sao terminais pelo mesmo criterio --
    o sweeper tambem ja nao as seleciona. Deixa-las fora da lista as
    esconderia do unico caminho de volta que existe.
    """
    return and_(
        Message.direction == MessageDirection.INBOUND,
        or_(
            Message.status == MessageStatus.ESGOTADA,
            and_(
                Message.status == MessageStatus.FAILED,
                Message.attempts >= get_settings().sweep_max_attempts,
            ),
        ),
    )


def _item(linha: Message) -> dict[str, object]:
    recebida: datetime = linha.created_at
    return {
        "id": str(linha.id),
        "canal": linha.channel,
        "status": linha.status,
        "tentativas": linha.attempts,
        "ultimoErro": linha.last_error,
        "recebidaEm": recebida.isoformat(),
    }


@router.get("/esgotadas")
async def listar_esgotadas(
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    _: IdentidadeDaRequisicao = _OPERADOR,
) -> dict[str, object]:
    """As mensagens na DLQ, as mais antigas primeiro -- sao as que esperam ha mais tempo."""
    async with get_sessionmaker()() as session:
        linhas = (
            await session.execute(
                select(Message)
                .where(_esgotada())
                .order_by(Message.created_at, Message.id)
                .limit(limite)
            )
        ).scalars()
        return {"itens": [_item(linha) for linha in linhas]}


@router.post("/{message_id}/reprocessar")
async def reprocessar(
    message_id: uuid.UUID,
    request: Request,
    _: IdentidadeDaRequisicao = _OPERADOR,
) -> dict[str, object]:
    """Devolve a mensagem ao pipeline com o orcamento de tentativas cheio.

    **RECEIVED, e nao QUEUED.** O job e enfileirado aqui, em melhor esforco;
    se o enqueue falhar, o sweeper pega uma RECEIVED em 30 s, e uma QUEUED so
    depois da janela de 300 s. `last_error` fica: e a historia de por que ela
    esteve na DLQ, e a proxima falha a sobrescreve.

    **O handoff aberto na falha continua existindo.** O corretor pode ja estar
    atendendo, e desfaze-lo tiraria a conversa dele. Se o turno reprocessado
    responder, o lead recebe a resposta; a reserva em `outbound_dispatches`
    impede que o aviso de erro saia de novo.

    **409** para mensagem que nao esta na DLQ: reprocessar uma que ainda esta
    no pipeline poria dois workers na mesma linha.
    """
    async with get_sessionmaker()() as session:
        resultado = await session.execute(
            update(Message)
            .where(Message.id == message_id, _esgotada())
            .values(status=MessageStatus.RECEIVED, attempts=0)
            .returning(Message.id)
        )
        devolvida = resultado.scalar_one_or_none()
        if devolvida is None:
            # O status e lido ANTES do rollback: o rollback expira a linha, e
            # le-la depois dispararia I/O fora da sessao.
            atual = await session.scalar(select(Message.status).where(Message.id == message_id))
            existe = await session.scalar(select(Message.id).where(Message.id == message_id))
            await session.rollback()
            if existe is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "mensagem nao encontrada")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"a mensagem nao esta na fila de esgotadas (status {atual})",
            )
        await session.commit()

    enfileirada = False
    pool = getattr(request.app.state, "redis_pool", None)
    if pool is not None:
        try:
            enfileirada = await enqueue_process_message(pool, message_id)
        except Exception:  # ampla de proposito: o sweeper e a rede, ver a docstring
            enfileirada = False
    return {
        "id": str(message_id),
        "status": MessageStatus.RECEIVED.value,
        "enfileirada": enfileirada,
    }
