"""As bordas que precisam do telefone do lead depois da TEC-203 (D4).

O par guarda o HMAC do valor cru, e o telefone so sai por `revelar` e
`telefones_de`. Estes testes semeiam a identidade e o vinculo direto no banco:
ate a entrada gravar a chave (Task 7 do plano), e esse o unico jeito de ter um
lead no formato novo.
"""

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.auditoria.vocabulario import CAMPO_TELEFONE
from mobia.domain.context.models import LeadQualification
from mobia.domain.crm.payload import VERSAO_DO_PAYLOAD, montar
from mobia.domain.handoff.dossie import Dossie
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.identidade.indice import chave_de, registrar, telefones_de
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.leads.consulta import montar_filtro
from mobia.domain.leads.repositorio import listar_leads, valor_revelado
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.status import MessageStatus
from mobia.domain.outbound.port import EnvioRecusado
from mobia.domain.outbound.whatsapp import WhatsAppOutbound
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


WA_ID_ESTRANGEIRO = "14155550100"


async def test_wa_id_estrangeiro_sai_cru_e_nao_nulo(session: AsyncSession) -> None:
    """`normalizar` so conhece telefone brasileiro, e o lead dos EUA no
    WhatsApp nao deixa de ter telefone por isso: o `wa_id` ja e E.164 sem o
    `+`, e e ele que CRM, e-mail e agenda recebem."""
    chave, _ = await _lead(session, CANAL_WHATSAPP, WA_ID_ESTRANGEIRO)
    par = (CANAL_WHATSAPP, chave)

    assert (await telefones_de(session, [par]))[par] == WA_ID_ESTRANGEIRO
    assert await valor_revelado(session, par=par, campo=CAMPO_TELEFONE) == f"+{WA_ID_ESTRANGEIRO}"


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


def _cliente_que_captura(capturado: dict[str, object]) -> httpx.AsyncClient:
    def _responde(requisicao: httpx.Request) -> httpx.Response:
        capturado.update(json.loads(requisicao.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(_responde))


async def test_envio_ao_whatsapp_vai_para_o_wa_id_cru(session: AsyncSession) -> None:
    """A Cloud API recebe o `wa_id` cru, e nao a chave -- ele so existe na
    memoria deste envio, revelado no ultimo instante por `_deliver`."""
    chave, _ = await _lead(session, CANAL_WHATSAPP, WA_ID_SEM_O_NOVE)
    corpo: dict[str, object] = {}
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=_cliente_que_captura(corpo))

    await outbound._deliver(uuid.uuid4(), "reply", {"para": chave, "de": "123", "texto": "oi"})

    assert corpo["to"] == WA_ID_SEM_O_NOVE


async def test_envio_sem_identidade_nao_chama_a_meta(session: AsyncSession) -> None:
    """Chave sem identidade e recusa permanente -- nunca chega a POST nenhum."""

    def _nunca_deveria_chamar(requisicao: httpx.Request) -> httpx.Response:
        raise AssertionError("nao deveria mandar POST algum sem identidade")

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(_nunca_deveria_chamar))
    outbound = WhatsAppOutbound(get_sessionmaker(), cliente=cliente)

    with pytest.raises(EnvioRecusado):
        await outbound._deliver(
            uuid.uuid4(), "reply", {"para": "f" * 64, "de": "123", "texto": "oi"}
        )


def _dossie(conversa: str) -> Dossie:
    """O minimo que `Dossie` exige, so para exercitar o campo `telefone` do payload."""
    return Dossie(
        canal=CANAL_WHATSAPP,
        conversa=conversa,
        primeira_mensagem_em=None,
        mensagens_do_lead=1,
        intencao=None,
        faixa_min_centavos=None,
        faixa_max_centavos=None,
        regiao=None,
        tipo_imovel=None,
        quartos=None,
        vagas=None,
        urgencia=None,
        forma_pagamento=None,
        tem_imovel_para_vender=None,
        score_total=None,
        score_fatores=(),
        score_causas=(),
        temperatura=None,
        temperatura_forcada_motivos=(),
        imoveis=(),
        campos_recusados=(),
        perguntados_sem_resposta=(),
        gatilho="LEAD_QUENTE",
        etiqueta="lead-quente",
        prioridade="NORMAL",
        criado_em=datetime(2026, 9, 26, tzinfo=UTC),
    )


async def test_payload_do_crm_leva_o_telefone() -> None:
    payload = montar(
        handoff_id=uuid.uuid4(),
        dossie=_dossie(chave_de(CANAL_WHATSAPP, TELEFONE)),
        telefone=TELEFONE,
        resumo=None,
        resumo_fallback=False,
    )

    assert payload["lead"]["telefone"] == f"+{TELEFONE}"
    assert payload["versao"] == VERSAO_DO_PAYLOAD == 2
