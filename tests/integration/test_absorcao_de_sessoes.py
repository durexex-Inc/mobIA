"""O turno do WhatsApp absorve as sessoes web vinculadas. TEC-129, D4."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from mobia.domain.context.models import LeadQualification
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker

WA_ID = "554899990000"  # a Meta entregando sem o 9
TELEFONE = "5548999990000"


async def _sessao_vinculada(session, **criterios) -> str:
    sessao = str(uuid.uuid4())
    evidencia = Message(
        channel=CANAL_WEB,
        conversation_key=sessao,
        sender_external_id=sessao,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.PROCESSED,
    )
    session.add(evidencia)
    if criterios:
        session.add(LeadQualification(channel=CANAL_WEB, conversation_key=sessao, **criterios))
    await session.commit()
    await vincular_sessao(
        get_sessionmaker(),
        channel=CANAL_WEB,
        conversation_key=sessao,
        telefone=TELEFONE,
        message_id=evidencia.id,
    )
    return sessao


async def _estado(session, channel: str, chave: str) -> LeadQualification | None:
    session.expire_all()
    return (
        await session.execute(
            select(LeadQualification).where(
                LeadQualification.channel == channel,
                LeadQualification.conversation_key == chave,
            )
        )
    ).scalar_one_or_none()


async def test_sem_vinculo_nao_faz_nada(session) -> None:
    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    assert pares == ()
    assert await _estado(session, CANAL_WHATSAPP, WA_ID) is None


async def test_wa_id_estrangeiro_nao_absorve(session) -> None:
    await _sessao_vinculada(session, quartos=2)

    assert (
        await absorver_sessoes_vinculadas(
            get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key="14155550123"
        )
        == ()
    )


async def test_preenche_o_whatsapp_vazio_e_devolve_os_pares(session) -> None:
    sessao = await _sessao_vinculada(session, quartos=2, regiao="Campeche")

    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    assert pares == ((CANAL_WEB, sessao),)
    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert estado is not None
    assert (estado.quartos, estado.regiao) == (2, "Campeche")


async def test_o_que_o_whatsapp_ja_sabe_prevalece(session) -> None:
    await _sessao_vinculada(session, quartos=2, regiao="Campeche")
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3))
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.quartos, estado.regiao) == (3, "Campeche")


async def test_recusas_se_somam(session) -> None:
    await _sessao_vinculada(session, campos_recusados=["faixa_preco"])
    session.add(
        LeadQualification(
            channel=CANAL_WHATSAPP, conversation_key=WA_ID, campos_recusados=["urgencia"]
        )
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert sorted(estado.campos_recusados) == ["faixa_preco", "urgencia"]


async def test_recusa_web_nao_volta_sobre_campo_preenchido(session) -> None:
    await _sessao_vinculada(session, campos_recusados=["quartos"])
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, quartos=3))
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert "quartos" not in (estado.campos_recusados or [])


async def test_recusa_do_orcamento_nao_volta_com_so_um_extremo_preenchido(session) -> None:
    """`faixa_preco_max` e a marca real gravada por `campos_a_recusar` -- ver
    `MARCA_DO_ORCAMENTO` em `domain/context/repositorio.py`. Ela cobre DUAS
    colunas (`_min_centavos` e `_max_centavos`), e o WhatsApp so respondeu uma
    delas: a recusa tem de cair do mesmo jeito, porque o vocabulario da marca
    nao distingue qual extremo foi respondido.
    """
    await _sessao_vinculada(session, campos_recusados=["faixa_preco_max"])
    session.add(
        LeadQualification(
            channel=CANAL_WHATSAPP, conversation_key=WA_ID, faixa_preco_max_centavos=500_00
        )
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert "faixa_preco_max" not in (estado.campos_recusados or [])


async def test_nao_grava_no_par_web(session) -> None:
    sessao = await _sessao_vinculada(session, quartos=2)
    session.add(LeadQualification(channel=CANAL_WHATSAPP, conversation_key=WA_ID, regiao="Centro"))
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    web = await _estado(session, CANAL_WEB, sessao)
    assert (web.quartos, web.regiao) == (2, None)


async def test_e_idempotente(session) -> None:
    await _sessao_vinculada(session, quartos=2, campos_recusados=["urgencia"])
    fabrica = get_sessionmaker()

    await absorver_sessoes_vinculadas(fabrica, channel=CANAL_WHATSAPP, conversation_key=WA_ID)
    await absorver_sessoes_vinculadas(fabrica, channel=CANAL_WHATSAPP, conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.quartos, estado.campos_recusados) == (2, ["urgencia"])


async def test_com_duas_sessoes_vale_a_mais_recente(session) -> None:
    await _sessao_vinculada(session, quartos=2)
    await _sessao_vinculada(session, quartos=4)
    # `updated_at` tem `server_default=now()`, e as duas linhas podem empatar na
    # mesma transacao do Postgres. Force a ordem em vez de depender do relogio.
    await session.execute(
        LeadQualification.__table__.update()
        .where(LeadQualification.quartos == 2)
        .values(updated_at=LeadQualification.updated_at - timedelta(hours=1))
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    assert (await _estado(session, CANAL_WHATSAPP, WA_ID)).quartos == 4


async def test_canal_que_nao_e_whatsapp_nao_absorve_nem_escreve(session) -> None:
    """Defesa em profundidade do gate do turno (D1): chamada com canal web, a
    absorcao devolve `()` sem tocar no banco -- mesmo com uma chave cujos
    digitos formam o telefone vinculado."""
    await _sessao_vinculada(session, quartos=2)

    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WEB, conversation_key=WA_ID
    )

    assert pares == ()
    assert await _estado(session, CANAL_WHATSAPP, WA_ID) is None
