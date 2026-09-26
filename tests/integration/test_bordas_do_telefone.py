"""As bordas que precisam do telefone do lead depois da TEC-203 (D4).

O par guarda o HMAC do valor cru, e o telefone so sai por `revelar` e
`telefones_de`. Estes testes semeiam a identidade e o vinculo direto no banco:
ate a entrada gravar a chave (Task 7 do plano), e esse o unico jeito de ter um
lead no formato novo.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.vocabulario import CAMPO_TELEFONE
from mobia.domain.context.models import LeadQualification
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.identidade.indice import registrar
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.leads.consulta import montar_filtro
from mobia.domain.leads.repositorio import listar_leads, valor_revelado
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.infra.db import get_sessionmaker

TELEFONE = "5548999990000"
WA_ID_SEM_O_NOVE = "554899990000"


async def _lead(session: AsyncSession, channel: str, valor: str) -> tuple[str, uuid.UUID]:
    """Um lead no formato da TEC-203: identidade e uma mensagem sob a chave."""
    chave = await registrar(session, channel, valor)
    mensagem = Message(
        channel=channel,
        conversation_key=chave,
        sender_external_id=chave,
        role=MessageRole.LEAD,
        direction=MessageDirection.INBOUND,
        content_type=MessageContentType.TEXTO,
        status=MessageStatus.PROCESSED,
    )
    session.add(mensagem)
    await session.commit()
    return chave, mensagem.id


async def _sessao_web(session: AsyncSession, *, telefone: str | None) -> str:
    chave, mensagem = await _lead(session, CANAL_WEB, str(uuid.uuid4()))
    if telefone is not None:
        await vincular_sessao(
            get_sessionmaker(),
            channel=CANAL_WEB,
            conversation_key=chave,
            telefone=telefone,
            message_id=mensagem,
        )
    return chave


async def test_busca_pelo_numero_com_o_nove_acha_wa_id_sem_o_nove(session: AsyncSession) -> None:
    await _lead(session, CANAL_WHATSAPP, WA_ID_SEM_O_NOVE)
    await _lead(session, CANAL_WHATSAPP, "5511988887777")

    pagina, _ = await listar_leads(session, filtro=montar_filtro(busca="(48) 99999-0000"))

    assert [lead.telefone for lead in pagina] == ["+55 48 9****-**00"]


async def test_busca_pelo_numero_acha_a_sessao_web_que_o_digitou(session: AsyncSession) -> None:
    await _sessao_web(session, telefone=TELEFONE)
    await _sessao_web(session, telefone="5511988887777")

    pagina, _ = await listar_leads(session, filtro=montar_filtro(busca="+55 48 99999-0000"))

    assert [(lead.channel, lead.telefone) for lead in pagina] == [(CANAL_WEB, "+55 48 9****-**00")]


async def test_busca_por_pedaco_do_numero_nao_acha(session: AsyncSession) -> None:
    """So numero completo: HMAC nao admite substring (decisao 3 do desenho)."""
    await _lead(session, CANAL_WHATSAPP, TELEFONE)
    await _sessao_web(session, telefone=TELEFONE)

    pagina, _ = await listar_leads(session, filtro=montar_filtro(busca="9999"))

    assert pagina == []


async def test_busca_por_bairro_continua_por_trecho(session: AsyncSession) -> None:
    chave, _ = await _lead(session, CANAL_WHATSAPP, TELEFONE)
    session.add(
        LeadQualification(channel=CANAL_WHATSAPP, conversation_key=chave, regiao="Campeche")
    )
    await session.commit()

    pagina, _ = await listar_leads(session, filtro=montar_filtro(busca="camp"))

    assert len(pagina) == 1


async def test_listagem_mascara_o_telefone_revelado(session: AsyncSession) -> None:
    await _lead(session, CANAL_WHATSAPP, TELEFONE)
    await _sessao_web(session, telefone="5511988887721")
    await _sessao_web(session, telefone=None)

    pagina, _ = await listar_leads(session, filtro=montar_filtro())

    assert sorted((lead.channel, lead.telefone or "") for lead in pagina) == [
        (CANAL_WEB, ""),
        (CANAL_WEB, "+55 11 9****-**21"),
        (CANAL_WHATSAPP, "+55 48 9****-**00"),
    ]


async def test_revelar_devolve_o_telefone_das_duas_origens(session: AsyncSession) -> None:
    do_whatsapp, _ = await _lead(session, CANAL_WHATSAPP, WA_ID_SEM_O_NOVE)
    com_vinculo = await _sessao_web(session, telefone="5511988887721")
    sem_vinculo = await _sessao_web(session, telefone=None)

    async def revelado(par: tuple[str, str]) -> str | None:
        return await valor_revelado(session, par=par, campo=CAMPO_TELEFONE)

    # O `wa_id` sem o 9 sai na forma canonica, com o 9.
    assert await revelado((CANAL_WHATSAPP, do_whatsapp)) == f"+{TELEFONE}"
    assert await revelado((CANAL_WEB, com_vinculo)) == "+5511988887721"
    assert await revelado((CANAL_WEB, sem_vinculo)) is None


async def test_revelar_chave_do_whatsapp_sem_identidade_e_nulo(session: AsyncSession) -> None:
    """`None` e "nao ha telefone", nunca a chave no lugar."""
    assert (
        await valor_revelado(session, par=(CANAL_WHATSAPP, "f" * 64), campo=CAMPO_TELEFONE) is None
    )


async def test_absorcao_casa_sessao_web_com_o_whatsapp_do_mesmo_numero(
    session: AsyncSession,
) -> None:
    sessao = await _sessao_web(session, telefone=TELEFONE)
    # O `wa_id` chegou sem o 9; o vinculo foi gravado com ele.
    do_whatsapp, _ = await _lead(session, CANAL_WHATSAPP, WA_ID_SEM_O_NOVE)

    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=do_whatsapp
    )

    assert pares == ((CANAL_WEB, sessao),)


async def test_absorcao_sem_identidade_nao_absorve(session: AsyncSession) -> None:
    await _sessao_web(session, telefone=TELEFONE)

    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key="f" * 64
    )

    assert pares == ()
