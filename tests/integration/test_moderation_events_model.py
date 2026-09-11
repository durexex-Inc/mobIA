import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.moderacao.models import ModerationEvent


async def test_a_linha_grava_e_o_carimbo_vem_do_servidor(session: AsyncSession) -> None:
    """`server_default` e nao valor do cliente, pelo motivo de `optout_events`:
    um relogio so, o do Postgres. Com o relogio de cada maquina escrevendo a
    coluna, um skew inverteria a ordem dos eventos de um mesmo lead.
    """
    evento = ModerationEvent(
        id=uuid.uuid4(),
        channel="whatsapp",
        conversation_key="5511911112222",
        direcao="ENTRADA",
        categoria="DISCRIMINACAO",
        message_id=uuid.uuid4(),
    )
    session.add(evento)
    await session.commit()

    gravado = await session.scalar(select(ModerationEvent))
    assert gravado is not None
    assert gravado.categoria == "DISCRIMINACAO"
    assert gravado.created_at is not None


async def test_message_id_nao_tem_fk_para_messages(session: AsyncSession) -> None:
    """Sem FK, pelo motivo escrito na migration 0010: a retencao de mensagens e
    de 12 meses (RNF-22) e a do registro de conformidade nao. Com FK, a limpeza
    de mensagens apagaria evidencia de recusa por cascata, ou travaria por
    restricao. Um `message_id` orfao e o preco, e e menor que o de perder a
    linha de auditoria junto com a mensagem que a originou.
    """
    evento = ModerationEvent(
        id=uuid.uuid4(),
        channel="whatsapp",
        conversation_key="5511911112222",
        direcao="SAIDA",
        categoria="NEGOCIACAO",
        message_id=uuid.uuid4(),  # nao existe em `messages`
    )
    session.add(evento)
    await session.commit()

    assert await session.scalar(select(ModerationEvent)) is not None
