"""O funil nao decresce, e por isso nenhuma conversao passa de 100%. TEC-367.

Molde de `test_repositorio_de_metricas.py`, que guarda as contagens cruas.
O que se afirma aqui e a propriedade que a acumulacao da D4 introduz, e os
dois casos que a produziam quebrada estao cada um num teste com o nome do
defeito que ele impede de voltar.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from conftest import _handoff_aceito, _lead, _recomendar  # type: ignore[import-not-found]

from mobia.domain.metricas.calculo import montar_funil
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import contar_etapas
from mobia.domain.metricas.vocabulario import ETAPAS, Etapa

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)


async def test_o_lead_que_qualifica_numa_mensagem_so_entra_em_em_conversa(session) -> None:
    """A segunda causa da docstring antiga, e a card pediu para reavaliar.

    Uma fala so nao passa o piso de `Em conversa`. Antes da acumulacao, esse
    lead ficava FORA daquela etapa e DENTRO de `Qualificado` -- e a conversao
    entre as duas dava 100% sobre zero, ou mais.
    """
    await _lead(session, conversa="5511900000001", falas=1, qualificado_em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.QUALIFICADO] == 1
    # Alcancou uma etapa posterior, entao passou por esta.
    assert etapas[Etapa.EM_CONVERSA] == 1
    assert etapas[Etapa.NOVO] == 1


async def test_o_recomendado_sem_carimbo_de_qualificacao_conta_como_qualificado(session) -> None:
    """A lacuna L1 vista pela outra ponta, e o que a acumulacao garante.

    Um lead recomendado cujo `qualificado_em` e nulo -- porque qualificou
    antes da migration `0040` e a trilha nao o alcancou -- nao pode fazer
    `Recomendado / Qualificado` dar 4000%. Ele chegou a Recomendado, logo
    passou por Qualificado.

    O backfill da `0055` conserta o DADO; esta propriedade e o que impede o
    residuo dele de voltar a estourar a taxa.
    """
    await _lead(session, conversa="5511900000001", falas=3)
    await _recomendar(session, conversa="5511900000001", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    assert etapas[Etapa.RECOMENDADO] == 1
    assert etapas[Etapa.QUALIFICADO] == 1


async def test_nenhuma_conversao_entre_consecutivas_passa_de_cem_por_cento(session) -> None:
    """O criterio de aceite da card, sobre a base que produzia o defeito.

    Quatro leads, cada um exercitando um dos caminhos que quebravam a
    monotonia: o que so falou, o que qualificou numa mensagem so, o
    recomendado sem carimbo, e o que chegou ao handoff aceito sem nada no
    meio.
    """
    await _lead(session, conversa="5511900000001", falas=1)
    await _lead(session, conversa="5511900000002", falas=1, qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000003", falas=1)
    await _recomendar(session, conversa="5511900000003", em=DENTRO)
    await _lead(session, conversa="5511900000004", falas=1)
    await _handoff_aceito(session, conversa="5511900000004", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())
    funil = montar_funil(etapas)

    for etapa in funil:
        if etapa.conversao_da_anterior is not None:
            assert etapa.conversao_da_anterior <= 1.0, f"{etapa.nome} converteu acima de 100%"


async def test_as_contagens_nao_crescem_ao_descer_o_funil(session) -> None:
    """A propriedade inteira, dita como propriedade e nao como exemplo.

    Mais forte que o criterio de aceite: ele fala de etapas CONSECUTIVAS, e
    esta asserta vale para o funil todo. `AGENDADO` e pulado -- ele nao tem
    fonte, e `montar_funil` o devolve nulo.
    """
    await _lead(session, conversa="5511900000001", falas=1, qualificado_em=DENTRO)
    await _lead(session, conversa="5511900000002", falas=5)
    await _recomendar(session, conversa="5511900000002", em=DENTRO)
    await _lead(session, conversa="5511900000003", falas=2)
    await _handoff_aceito(session, conversa="5511900000003", em=DENTRO)

    etapas = await contar_etapas(session, recorte=_recorte())

    contagens = [etapas[etapa] for etapa in ETAPAS if etapa in etapas]
    assert contagens == sorted(contagens, reverse=True), contagens
