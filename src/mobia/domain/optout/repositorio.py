"""Grava, reverte e consulta o estado de opt-out de um lead.

Nenhuma das duas escritas passa `created_at`: a coluna tem
`server_default=func.now()` e quem carimba e o Postgres. Ver a nota em
`OptoutEvent.created_at` -- com o relogio do cliente, skew entre a maquina que
grava o opt-out e a que roda a reativacao inverte a ordem dos eventos, e a
ordem **e** o estado nesta tabela.

As duas escritas recebem `session_factory` e commitam sozinhas, como
`marcar_bloqueada`: sao atos completos em si, e quem chama nao tem transacao
para compartilhar. As duas leituras recebem `session` porque rodam dentro da
sessao de quem pergunta -- a guarda na porta de saida ja tem uma aberta.

Desde a TEC-206 cada escrita grava tambem o seu registro na trilha de
auditoria, na MESMA sessao da linha de `optout_events` e antes do commit: ou
os dois existem, ou nenhum. O ator e SISTEMA nas duas -- no opt-out o lead
pediu e o sistema registrou; na reativacao o operador da CLI e um `autor` em
texto livre, nao um `usuario_id`. O `motivo` nao vai para a trilha (D5): ele
fica aqui, e o registro aponta para esta linha pelo id.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.auditoria.registro import registrar_evento
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA, Acao, Entidade
from mobia.domain.messages.models import Message
from mobia.domain.optout.models import EVENTO_OPT_OUT, EVENTO_REATIVACAO, OptoutEvent


async def registrar_optout(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    message_id: uuid.UUID,
) -> None:
    """Acrescenta o evento de opt-out. Nunca atualiza nada."""
    evento_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=evento_id,
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_OPT_OUT,
                message_id=message_id,
            )
        )
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REGISTRADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(evento_id),
            lead=(channel, conversation_key),
        )
        await session.commit()


async def reativar(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    channel: str,
    conversation_key: str,
    autor: str,
    motivo: str,
) -> None:
    """Acrescenta o evento de reativacao, com quem mandou e por que.

    `autor` e `motivo` nao tem default: a RN-14.3 exige justificativa, e um
    default vazio a tornaria decorativa.
    """
    evento_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            OptoutEvent(
                id=evento_id,
                channel=channel,
                conversation_key=conversation_key,
                evento=EVENTO_REATIVACAO,
                autor=autor,
                motivo=motivo,
            )
        )
        await registrar_evento(
            session,
            ator=ATOR_SISTEMA,
            acao=Acao.OPTOUT_REATIVADO,
            entidade=Entidade.OPTOUT_EVENT,
            entidade_id=str(evento_id),
            lead=(channel, conversation_key),
        )
        await session.commit()


async def esta_em_optout(session: AsyncSession, *, channel: str, conversation_key: str) -> bool:
    """O ultimo evento deste lead e um opt-out.

    Sem evento nenhum, nao esta -- o estado default e "pode receber".
    """
    ultimo = (
        await session.execute(
            select(OptoutEvent.evento)
            .where(
                OptoutEvent.channel == channel,
                OptoutEvent.conversation_key == conversation_key,
            )
            .order_by(OptoutEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return ultimo == EVENTO_OPT_OUT


async def esta_em_optout_por_mensagem(session: AsyncSession, message_id: uuid.UUID) -> bool:
    """A mesma pergunta, para quem so tem o id da mensagem.

    E o caso da guarda em `GuardedOutbound.send`, cuja assinatura nao carrega o
    par do lead. Mensagem inexistente devolve False: se nao ha lead, nao ha
    opt-out a respeitar, e recusar o envio por isso esconderia o defeito real.
    """
    lead = (
        await session.execute(
            select(Message.channel, Message.conversation_key).where(Message.id == message_id)
        )
    ).one_or_none()
    if lead is None:
        return False
    return await esta_em_optout(
        session, channel=lead.channel, conversation_key=lead.conversation_key
    )
