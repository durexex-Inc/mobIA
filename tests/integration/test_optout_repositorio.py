import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.optout.models import OptoutEvent
from mobia.domain.optout.repositorio import (
    esta_em_optout,
    reativar,
    registrar_optout,
)

CANAL = "wa"
CHAVE = "5548999998888"


async def test_sem_evento_nenhum_o_lead_nao_esta_em_optout(session: AsyncSession) -> None:
    assert await esta_em_optout(session, channel=CANAL, conversation_key=CHAVE) is False


async def test_depois_do_optout_o_lead_esta_silenciado(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=CHAVE, message_id=uuid.uuid4()
    )

    assert await esta_em_optout(session, channel=CANAL, conversation_key=CHAVE) is True


async def test_o_estado_e_o_ultimo_evento_e_o_historico_fica_inteiro(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Opt-out, reativacao, opt-out de novo: tres linhas, e vale a ultima.

    E o teste que prova por que a tabela e append-only. Com coluna booleana o
    primeiro opt-out teria sido sobrescrito pela reativacao, e a evidencia de
    conformidade -- que a RN-14.2 exige -- teria sido apagada por um UPDATE.
    """
    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=CHAVE, message_id=uuid.uuid4()
    )
    await reativar(
        session_factory,
        channel=CANAL,
        conversation_key=CHAVE,
        autor="Paulo M.",
        motivo="pediu por telefone",
    )
    assert await esta_em_optout(session, channel=CANAL, conversation_key=CHAVE) is False

    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=CHAVE, message_id=uuid.uuid4()
    )

    assert await esta_em_optout(session, channel=CANAL, conversation_key=CHAVE) is True
    total = (await session.execute(select(func.count()).select_from(OptoutEvent))).scalar_one()
    assert total == 3


async def test_o_optout_de_um_lead_nao_silencia_outro(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=CHAVE, message_id=uuid.uuid4()
    )

    assert await esta_em_optout(session, channel=CANAL, conversation_key="5548911112222") is False
    assert await esta_em_optout(session, channel="web", conversation_key=CHAVE) is False
