import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.optout.models import OptoutEvent
from mobia.domain.optout.repositorio import (
    esta_em_optout,
    esta_em_optout_por_mensagem,
    reativar,
    registrar_optout,
)

CANAL = "wa"
CHAVE = "5548999998888"


def _mensagem_do_lead(*, channel: str = CANAL, conversation_key: str = CHAVE) -> Message:
    """Uma `Message` minima, so com as colunas obrigatorias.

    Sem `text_body`: o teste nao precisa de conteudo, e gerar um cifrado real
    (`encrypt`/`aad_de`) so acrescentaria ruido a um teste que e sobre a
    lookup por `message_id`, nao sobre o corpo da fala.
    """
    return Message(
        id=uuid.uuid4(),
        channel=channel,
        conversation_key=conversation_key,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        text_body=None,
        raw_payload=None,
        status=None,
    )


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


async def test_por_mensagem_de_lead_sem_optout_devolve_false(session: AsyncSession) -> None:
    mensagem = _mensagem_do_lead()
    session.add(mensagem)
    await session.commit()

    assert await esta_em_optout_por_mensagem(session, mensagem.id) is False


async def test_por_mensagem_de_lead_com_optout_devolve_true(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    mensagem = _mensagem_do_lead()
    session.add(mensagem)
    await session.commit()

    await registrar_optout(
        session_factory, channel=CANAL, conversation_key=CHAVE, message_id=uuid.uuid4()
    )

    assert await esta_em_optout_por_mensagem(session, mensagem.id) is True


async def test_por_mensagem_inexistente_e_fail_open(session: AsyncSession) -> None:
    """`message_id` que nao existe no banco devolve False -- fail-open deliberado.

    Sem lead nenhum atras do id, nao ha opt-out a respeitar: a mensagem nao
    aponta para nenhum `(channel, conversation_key)`, entao nao ha estado para
    consultar. Recusar o envio neste caso nao protege lead nenhum -- so
    esconderia o defeito real, que e algum chamador passando um `message_id`
    que nunca foi gravado. Este teste e a prova de que a escolha foi
    deliberada, e nao um acidente que ninguem notou.
    """
    assert await esta_em_optout_por_mensagem(session, uuid.uuid4()) is False
