"""As contagens do funil contra o banco. TEC-190, RN-17.2 e D10 (coorte)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import _corretor, _handoff_aceito, _lead, _recomendar

from mobia.domain.agente.schemas import Intencao
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import contar_etapas
from mobia.domain.metricas.vocabulario import Etapa

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
FORA = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)


async def test_a_coorte_e_quem_nasceu_no_periodo(session) -> None:
    await _lead(session, conversa="5511900000001", nasceu_em=DENTRO)
    await _lead(session, conversa="5511900000002", nasceu_em=FORA)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 1


async def test_em_conversa_exige_mais_de_uma_fala_do_lead(session) -> None:
    await _lead(session, conversa="5511900000001", falas=1)
    await _lead(session, conversa="5511900000002", falas=3)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 2
    assert etapas[Etapa.EM_CONVERSA] == 1


async def test_qualificado_sai_do_carimbo_e_nao_de_updated_at(session) -> None:
    await _lead(session, conversa="5511900000001", qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000002")

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.QUALIFICADO] == 1


async def test_lead_da_coorte_que_qualificou_depois_do_periodo_conta(session) -> None:
    """Coorte: a etapa mede se o lead CHEGOU la, nao quando. D10."""
    await _lead(
        session,
        conversa="5511900000001",
        nasceu_em=DENTRO,
        qualificado_em=datetime(2026, 10, 5, 12, 0, tzinfo=UTC),
    )

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.QUALIFICADO] == 1


async def test_recomendado_conta_quem_recebeu_ficha(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _recomendar(session, conversa="5511900000001", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.RECOMENDADO] == 1


async def test_duas_recomendacoes_para_o_mesmo_lead_contam_um(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _recomendar(session, conversa="5511900000001", em=DENTRO)
    await _recomendar(session, conversa="5511900000001", em=DENTRO + timedelta(hours=1))

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.RECOMENDADO] == 1


async def test_handoff_aceito_conta_so_o_aceito(session) -> None:
    await _lead(session, conversa="5511900000001")
    await _lead(session, conversa="5511900000002")
    await _handoff_aceito(session, conversa="5511900000001", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.HANDOFF_ACEITO] == 1


async def test_agendado_nao_aparece_nas_contagens(session) -> None:
    """Nao ha consulta para ele -- o `montar_funil` e quem poe o nulo."""
    await _lead(session, conversa="5511900000001")

    etapas = await contar_etapas(session, recorte=_recorte())

    assert Etapa.AGENDADO not in etapas


async def test_filtro_por_canal_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", canal="whatsapp")
    await _lead(session, conversa="5511900000002", canal="web")

    etapas = await contar_etapas(session, recorte=_recorte(canal="web"))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_temperatura_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", temperatura="QUENTE")
    await _lead(session, conversa="5511900000002", temperatura="FRIO")

    etapas = await contar_etapas(session, recorte=_recorte(temperatura="QUENTE"))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_intencao_recorta_a_coorte(session) -> None:
    await _lead(session, conversa="5511900000001", intencao=Intencao.COMPRA.value)
    await _lead(session, conversa="5511900000002", intencao=Intencao.ALUGUEL.value)

    etapas = await contar_etapas(session, recorte=_recorte(intencao=Intencao.COMPRA.value))

    assert etapas[Etapa.NOVO] == 1


async def test_filtro_por_corretor_alcanca_as_etapas_anteriores(session) -> None:
    """D6: o funil e o dos leads QUE ACABARAM com aquele corretor.

    O lead nao tem dono antes do repasse, entao filtrar por corretor conta a
    mesma conversa nos estagios anteriores ao handoff dele.
    """
    corretor = await _corretor(session)
    outro = await _corretor(session)
    await _lead(session, conversa="5511900000001", falas=3)
    await _lead(session, conversa="5511900000002", falas=3)
    await _handoff_aceito(session, conversa="5511900000001", em=DENTRO, corretor_id=corretor)
    await _handoff_aceito(session, conversa="5511900000002", em=DENTRO, corretor_id=outro)

    etapas = await contar_etapas(session, recorte=_recorte(corretor_id=corretor))

    assert etapas[Etapa.NOVO] == 1
    assert etapas[Etapa.EM_CONVERSA] == 1
    assert etapas[Etapa.HANDOFF_ACEITO] == 1


async def test_lead_sem_handoff_some_do_filtro_por_corretor(session) -> None:
    """Lacuna L2, escrita como teste para nao ser descoberta como surpresa."""
    await _lead(session, conversa="5511900000001")

    etapas = await contar_etapas(session, recorte=_recorte(corretor_id=uuid.uuid4()))

    assert etapas[Etapa.NOVO] == 0


async def test_periodo_sem_lead_devolve_zeros_e_nao_erro(session) -> None:
    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 0
    assert etapas[Etapa.HANDOFF_ACEITO] == 0


async def test_a_fronteira_do_dia_e_a_do_fuso(session) -> None:
    """2026-08-01 01:00Z e 31/07 22:00 em Sao Paulo: esta FORA de agosto."""
    await _lead(session, conversa="5511900000001", nasceu_em=datetime(2026, 8, 1, 1, 0, tzinfo=UTC))
    await _lead(session, conversa="5511900000002", nasceu_em=datetime(2026, 8, 1, 5, 0, tzinfo=UTC))

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.NOVO] == 1
