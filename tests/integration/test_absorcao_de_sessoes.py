"""O turno do WhatsApp absorve as sessoes web vinculadas. TEC-129, D4."""

import uuid
from datetime import timedelta
from typing import Any

from conftest import ClassificadorFake, ContadorFake, ModeradorFake, ResumidorFake
from sqlalchemy import select

from mobia.domain.agendamento.agendador import AgendadorDeConfirmacaoNoop
from mobia.domain.agente.investidor import Horizonte, PerfilInvestidor, RetornoEsperadoTipo
from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.repositorio import MARCA_DO_ORCAMENTO, aplicar_mudanca_de_intencao
from mobia.domain.handoff.agendador import AgendadorNoop
from mobia.domain.identidade.absorcao import absorver_sessoes_vinculadas
from mobia.domain.identidade.models import VinculoDeSessao
from mobia.domain.identidade.repositorio import vincular_sessao
from mobia.domain.messages.canais import CANAL_WEB, CANAL_WHATSAPP
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.messages.schemas import ParsedMessage
from mobia.domain.messages.service import IngestionService
from mobia.domain.messages.status import MessageStatus
from mobia.domain.optout.repositorio import esta_em_optout, registrar_optout
from mobia.domain.outbound.presenca import IndicadorNoop
from mobia.domain.outbound.roteador import RoteadorPorCanal
from mobia.domain.outbound.web import WebOutbound
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.process_message import process_message

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


# --- banda de intencao (revisao final da TEC-129, I1) -----------------------
#
# Orcamento dito sob uma banda nao significa nada na outra (TEC-136,
# `mudou_de_banda`). A absorcao nao pode trazer para um WhatsApp de aluguel o
# orcamento que a mesma pessoa deu no site procurando compra.

NOVECENTOS_MIL = 900_000_00


async def test_orcamento_de_compra_nao_atravessa_para_whatsapp_de_aluguel(session) -> None:
    await _sessao_vinculada(
        session,
        intencao=Intencao.COMPRA.value,
        faixa_preco_max_centavos=NOVECENTOS_MIL,
        campos_recusados=[MARCA_DO_ORCAMENTO, "urgencia"],
        quartos=2,
    )
    session.add(
        LeadQualification(
            channel=CANAL_WHATSAPP, conversation_key=WA_ID, intencao=Intencao.ALUGUEL.value
        )
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.faixa_preco_min_centavos, estado.faixa_preco_max_centavos) == (None, None)
    # A recusa do orcamento tambem e da banda; a de urgencia nao, e atravessa.
    assert estado.campos_recusados == ["urgencia"]
    # O criterio que nao depende de banda continua chegando.
    assert estado.quartos == 2


async def test_orcamento_descartado_pela_troca_de_intencao_nao_volta_da_sessao_web(
    session,
) -> None:
    await _sessao_vinculada(
        session, intencao=Intencao.COMPRA.value, faixa_preco_max_centavos=NOVECENTOS_MIL
    )
    fabrica = get_sessionmaker()

    # Turno 1: o WhatsApp herda a compra e o orcamento dela.
    await absorver_sessoes_vinculadas(fabrica, channel=CANAL_WHATSAPP, conversation_key=WA_ID)
    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.intencao, estado.faixa_preco_max_centavos) == (
        Intencao.COMPRA.value,
        NOVECENTOS_MIL,
    )

    # O lead passa a falar de aluguel: o caminho real do turno descarta a faixa
    # e `gravar_estado` grava a intencao nova, na mesma transacao.
    async with fabrica() as sessao_do_turno:
        mudanca = await aplicar_mudanca_de_intencao(
            sessao_do_turno,
            channel=CANAL_WHATSAPP,
            conversation_key=WA_ID,
            intencao=Intencao.ALUGUEL,
        )
        assert mudanca is not None and mudanca.faixa_descartada
        await sessao_do_turno.execute(
            LeadQualification.__table__.update()
            .where(
                LeadQualification.channel == CANAL_WHATSAPP,
                LeadQualification.conversation_key == WA_ID,
            )
            .values(intencao=Intencao.ALUGUEL.value)
        )
        await sessao_do_turno.commit()

    # Turno 2: a absorcao roda de novo e ve a faixa vazia -- e nao a repreenche.
    await absorver_sessoes_vinculadas(fabrica, channel=CANAL_WHATSAPP, conversation_key=WA_ID)

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.intencao, estado.faixa_preco_max_centavos) == (Intencao.ALUGUEL.value, None)


async def test_sem_intencao_no_whatsapp_a_intencao_herdada_define_a_banda(session) -> None:
    # A mais recente diz aluguel e nao deu orcamento; a mais antiga, de compra,
    # deu. A intencao herdada e a de aluguel, e o orcamento de compra fica.
    await _sessao_vinculada(
        session, intencao=Intencao.COMPRA.value, faixa_preco_max_centavos=NOVECENTOS_MIL
    )
    await _sessao_vinculada(session, intencao=Intencao.ALUGUEL.value)
    await session.execute(
        LeadQualification.__table__.update()
        .where(LeadQualification.intencao == Intencao.COMPRA.value)
        .values(updated_at=LeadQualification.updated_at - timedelta(hours=1))
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.intencao, estado.faixa_preco_max_centavos) == (Intencao.ALUGUEL.value, None)


async def test_campos_de_investidor_vem_de_uma_sessao_so(session) -> None:
    # Duas sessoes parciais: a mais recente disse so o horizonte; a mais
    # antiga, o tipo de retorno -- e o perfil derivado DO horizonte dela.
    # Misturar campo a campo juntaria o horizonte de uma ao perfil da outra.
    await _sessao_vinculada(
        session,
        intencao=Intencao.INVESTIMENTO.value,
        horizonte=Horizonte.CURTO.value,
        retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL.value,
        perfil_investidor=PerfilInvestidor.RENDA.value,
    )
    await _sessao_vinculada(
        session, intencao=Intencao.INVESTIMENTO.value, horizonte=Horizonte.LONGO.value
    )
    await session.execute(
        LeadQualification.__table__.update()
        .where(LeadQualification.horizonte == Horizonte.CURTO.value)
        .values(updated_at=LeadQualification.updated_at - timedelta(hours=1))
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.horizonte, estado.retorno_esperado_tipo, estado.perfil_investidor) == (
        Horizonte.LONGO.value,
        None,
        None,
    )


async def test_campos_de_investidor_nao_completam_o_que_o_whatsapp_comecou(session) -> None:
    # O WhatsApp ja disse o horizonte; a sessao web traz tipo de retorno e um
    # perfil derivado de OUTRO horizonte. Completar faria o perfil mentir.
    await _sessao_vinculada(
        session,
        intencao=Intencao.INVESTIMENTO.value,
        horizonte=Horizonte.CURTO.value,
        retorno_esperado_tipo=RetornoEsperadoTipo.ALUGUEL.value,
        perfil_investidor=PerfilInvestidor.RENDA.value,
    )
    session.add(
        LeadQualification(
            channel=CANAL_WHATSAPP,
            conversation_key=WA_ID,
            intencao=Intencao.INVESTIMENTO.value,
            horizonte=Horizonte.LONGO.value,
        )
    )
    await session.commit()

    await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.horizonte, estado.retorno_esperado_tipo, estado.perfil_investidor) == (
        Horizonte.LONGO.value,
        None,
        None,
    )


async def test_so_as_tres_sessoes_vinculadas_mais_recentes_contam(session) -> None:
    """Revisao final da TEC-129 (I2): qualquer um que saiba o numero vincula
    sessoes a ele, entao o fan-in tem teto."""
    mais_antiga = await _sessao_vinculada(session, regiao="Campeche")
    recentes = [await _sessao_vinculada(session, quartos=2) for _ in range(3)]
    # `criado_em` tem `server_default=now()`; force a ordem em vez de depender
    # do relogio entre transacoes.
    await session.execute(
        VinculoDeSessao.__table__.update()
        .where(VinculoDeSessao.conversation_key == mais_antiga)
        .values(criado_em=VinculoDeSessao.criado_em - timedelta(days=1))
    )
    await session.commit()

    pares = await absorver_sessoes_vinculadas(
        get_sessionmaker(), channel=CANAL_WHATSAPP, conversation_key=WA_ID
    )

    assert {chave for _, chave in pares} == set(recentes)
    estado = await _estado(session, CANAL_WHATSAPP, WA_ID)
    assert (estado.quartos, estado.regiao) == (2, None)


class _WhatsAppQueRegistra:
    """A porta da Meta que registra o envio em vez de falhar."""

    def __init__(self) -> None:
        self.envios: list[dict[str, Any]] = []

    async def send(self, message_id: Any, kind: str, payload: dict[str, Any]) -> bool:
        self.envios.append(payload)
        return True


async def test_optout_no_par_web_nao_silencia_o_turno_do_whatsapp(session, redis_pool) -> None:
    """D4: uma sessao nao verificada nao silencia o numero de outra pessoa. O
    opt-out fica no par web, e o turno do WhatsApp responde normalmente."""
    sessao = await _sessao_vinculada(session, quartos=2)
    evidencia = await session.scalar(select(Message.id).where(Message.conversation_key == sessao))
    fabrica = get_sessionmaker()
    await registrar_optout(
        fabrica, channel=CANAL_WEB, conversation_key=sessao, message_id=evidencia
    )

    [message_id] = await IngestionService(fabrica, redis_pool).ingest(
        [
            ParsedMessage(
                provider_message_id=f"wamid.{uuid.uuid4()}",
                sender_external_id=WA_ID,
                recipient_external_id="phone-number-id",
                content_type=MessageContentType.TEXTO,
                text_body="oi, vim do site",
                raw_payload={},
            )
        ],
        channel=CANAL_WHATSAPP,
    )
    whatsapp = _WhatsAppQueRegistra()
    ctx = {
        "session_factory": fabrica,
        "outbound": RoteadorPorCanal(
            fabrica, {CANAL_WHATSAPP: whatsapp, CANAL_WEB: WebOutbound(fabrica, redis_pool)}
        ),
        "classificador": ClassificadorFake(),
        "resumidor": ResumidorFake(),
        "contador": ContadorFake(),
        "moderador": ModeradorFake(),
        "agendador": AgendadorNoop(),
        "agendador_de_confirmacao": AgendadorDeConfirmacaoNoop(),
        "indicadores": {CANAL_WHATSAPP: IndicadorNoop(), CANAL_WEB: IndicadorNoop()},
    }

    assert await process_message(ctx, str(message_id)) == "respondido"
    assert whatsapp.envios
    # A absorcao rodou nesse turno -- o opt-out nao passou por ela.
    assert (await _estado(session, CANAL_WHATSAPP, WA_ID)).quartos == 2
    async with fabrica() as sessao_db:
        assert not await esta_em_optout(sessao_db, channel=CANAL_WHATSAPP, conversation_key=WA_ID)
