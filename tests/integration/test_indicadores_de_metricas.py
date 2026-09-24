"""Os indicadores da RN-17.1 contra o banco. TEC-190."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import _falar, _handoff_aceito, _lead

from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.messages.enums import MessageDirection
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa

CANAL = "whatsapp"
SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)


async def _indicadores(session, **extra):
    recorte = _recorte(**extra)
    etapas = await contar_etapas(session, recorte=recorte)
    return await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])


async def _responder(session, *, conversa: str, em: datetime) -> None:
    """A saida do agente. `_falar` do conftest ja sabe montar as duas direcoes."""
    await _falar(session, conversa=conversa, em=em, direcao=MessageDirection.OUTBOUND)
    await session.commit()


async def test_conversas_ativas_conta_so_as_nao_encerradas(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    conversa = await session.get(Conversa, (CANAL, "5511900000002"))
    assert conversa is not None
    conversa.status = Status.ENCERRADA
    conversa.motivo_do_encerramento = MotivoDoEncerramento.INATIVIDADE
    conversa.encerrada_em = DENTRO
    await session.commit()

    indicadores = await _indicadores(session)

    assert indicadores.conversas_ativas == 1


async def test_taxa_de_qualificacao_e_sobre_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000002")
    await _lead(session, conversa="5511900000003")
    await _lead(session, conversa="5511900000004")

    indicadores = await _indicadores(session)

    assert indicadores.taxa_qualificacao == 0.25


async def test_coorte_vazia_da_taxa_nula_e_nao_zero(session) -> None:
    """0/0 nao e 0%. Item 5 do Review Focus."""
    indicadores = await _indicadores(session)

    assert indicadores.taxa_qualificacao is None


async def test_distribuicao_por_temperatura_traz_as_faixas_presentes(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura="QUENTE")
    await _lead(session, conversa="5511900000002", temperatura="QUENTE")
    await _lead(session, conversa="5511900000003", temperatura="FRIO")

    indicadores = await _indicadores(session)

    assert indicadores.distribuicao_por_temperatura == {"QUENTE": 2, "FRIO": 1}


async def test_lead_sem_temperatura_nao_entra_na_distribuicao(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura=None)

    indicadores = await _indicadores(session)

    assert indicadores.distribuicao_por_temperatura == {}


async def test_tempo_de_primeira_resposta_e_da_primeira_fala_ate_a_primeira_saida(
    session,
) -> None:
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _responder(session, conversa="5511900000001", em=DENTRO + timedelta(seconds=30))

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_primeira_resposta_seg == 30.0


async def test_lead_sem_resposta_nao_entra_na_media(session) -> None:
    """Media sobre quem FOI respondido: incluir o nao respondido como zero
    baixaria a media justamente quando o atendimento esta pior.
    """
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _responder(session, conversa="5511900000001", em=DENTRO + timedelta(seconds=30))
    await _lead(session, conversa="5511900000002", nasceu_em=DENTRO)

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_primeira_resposta_seg == 30.0


async def test_tempo_de_qualificacao_e_do_nascimento_ate_o_carimbo(session) -> None:
    await _lead(
        session,
        conversa="5511900000001",
        nasceu_em=DENTRO,
        qualificado_em=DENTRO + timedelta(minutes=10),
    )

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_qualificacao_seg == 600.0


async def test_ninguem_qualificado_da_tempo_nulo(session) -> None:
    await _lead(session, conversa="5511900000001")

    indicadores = await _indicadores(session)

    assert indicadores.tempo_medio_qualificacao_seg is None


async def test_sla_exclui_o_handoff_sem_limite_do_denominador(session) -> None:
    """Emenda E-01 da RN-16.3: `sla_limite_em` nulo sai `dentroDoSla` true por
    VACUIDADE, nunca por pontualidade. Incluir infla a taxa.
    """
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _lead(session, conversa="5511900000003")
    # No prazo.
    await _handoff_aceito(
        session,
        conversa="5511900000001",
        em=DENTRO,
        sla_limite_em=DENTRO + timedelta(hours=1),
    )
    # Fora do prazo.
    await _handoff_aceito(
        session,
        conversa="5511900000002",
        em=DENTRO + timedelta(hours=2),
        sla_limite_em=DENTRO + timedelta(hours=1),
    )
    # Escalado sem destinatario: `sla_limite_em` nulo para sempre.
    await _handoff_aceito(session, conversa="5511900000003", em=DENTRO, sla_limite_em=None)

    indicadores = await _indicadores(session)

    # 1 de 2, e nao 2 de 3.
    assert indicadores.sla_handoff_cumprido_pct == 0.5


async def test_sem_handoff_com_prazo_a_taxa_e_nula(session) -> None:
    await _lead(session, conversa="5511900000001")

    indicadores = await _indicadores(session)

    assert indicadores.sla_handoff_cumprido_pct is None
