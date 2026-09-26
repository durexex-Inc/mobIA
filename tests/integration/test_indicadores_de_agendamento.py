"""Os quatro indicadores de agendamento, contra o banco. TEC-376, RN-17.1.

Os cenarios do Gherkin da card, mais o que a D4 do desenho promete e o
Gherkin nao cobre: a cadeia de tres, o `EXPIRADO` de fora e o denominador
zero.

**A remarcacao e montada por `ciclo.py::remarcar`, e nao por INSERT a mao.**
O direito de contar sem CTE recursivo vem da maquina de estados daquele
modulo (D4); um teste que montasse a cadeia por fora continuaria verde no dia
em que ela mudasse, que e justamente o dia em que estas contagens passam a
contar duplicado.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from conftest import _agendar, _corretor, _lead

from mobia.domain.agendamento.ciclo import marcar_realizado, remarcar
from mobia.domain.agendamento.janelas import Intervalo
from mobia.domain.agendamento.models import StatusDoAgendamento
from mobia.domain.metricas.filtros import montar_recorte
from mobia.domain.metricas.repositorio import calcular_indicadores, contar_etapas
from mobia.domain.metricas.vocabulario import Etapa

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
DENTRO = datetime(2026, 8, 10, 15, 0, tzinfo=UTC)
FORA = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)
VISITA = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
CONVERSA = "5511900000001"


def _recorte(**extra):
    return montar_recorte(de=date(2026, 8, 1), ate=date(2026, 8, 31), fuso=SAO_PAULO, **extra)


async def _indicadores(session):
    recorte = _recorte()
    etapas = await contar_etapas(session, recorte=recorte)
    return await calcular_indicadores(session, recorte=recorte, novos=etapas[Etapa.NOVO])


async def test_o_painel_conta_criados_e_confirmados(session) -> None:
    """Cenario 1 do Gherkin: tres criados, dois confirmados."""
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    await _agendar(
        session, conversa=CONVERSA, corretor_id=corretor, status=StatusDoAgendamento.RESERVADO
    )
    for dia in (1, 2):
        await _agendar(
            session,
            conversa=CONVERSA,
            corretor_id=corretor,
            inicio=VISITA + timedelta(days=dia),
        )

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_criados == 3
    assert indicadores.agendamentos_confirmados == 2


async def test_a_taxa_de_no_show_sai_dos_desfechos(session) -> None:
    """Cenario 2 do Gherkin: quatro com horario passado, um NO_SHOW."""
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    for dia in range(3):
        await _agendar(
            session,
            conversa=CONVERSA,
            corretor_id=corretor,
            status=StatusDoAgendamento.REALIZADO,
            inicio=VISITA + timedelta(days=dia),
        )
    await _agendar(
        session,
        conversa=CONVERSA,
        corretor_id=corretor,
        status=StatusDoAgendamento.NO_SHOW,
        inicio=VISITA + timedelta(days=3),
    )

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_realizados == 3
    assert indicadores.taxa_no_show == 0.25


async def test_remarcacao_nao_conta_duas_vezes(session) -> None:
    """Cenario 3 do Gherkin, montado pela transicao de verdade.

    O original vira REAGENDADO e o sucessor nasce apontando para ele; os dois
    sao o MESMO compromisso, e uma contagem que somasse os dois estaria errada
    em favor do produto.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    original = await _agendar(session, conversa=CONVERSA, corretor_id=corretor)

    remarcado = await remarcar(
        session,
        agendamento_id=original,
        janela=Intervalo(VISITA + timedelta(days=1), VISITA + timedelta(days=1, hours=1)),
        agora=VISITA,
    )
    # **Depois do inicio do SUCESSOR**, que e um dia adiante do original. A
    # guarda da TEC-374 recusa marcar desfecho de visita que ainda nao
    # comecou, e esta asserta marcava o sucessor com o relogio do original --
    # o mesmo defeito latente que aquela card achou nos testes da TEC-172.
    await marcar_realizado(
        session, agendamento_id=remarcado.novo_id, agora=VISITA + timedelta(days=1, hours=2)
    )
    await session.commit()

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_criados == 1
    assert indicadores.agendamentos_confirmados == 1
    assert indicadores.agendamentos_realizados == 1


async def test_a_cadeia_de_tres_tambem_conta_uma_vez(session) -> None:
    """A -> B -> C, que o Gherkin nao cobre e a D4 promete.

    `ciclo.py::remarcar` nao tem teto de cadeia. Contar raizes vale para
    qualquer comprimento sem tratamento especial -- e o que dispensa o CTE
    recursivo.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    atual = await _agendar(session, conversa=CONVERSA, corretor_id=corretor)

    for dia in (1, 2):
        remarcado = await remarcar(
            session,
            agendamento_id=atual,
            janela=Intervalo(VISITA + timedelta(days=dia), VISITA + timedelta(days=dia, hours=1)),
            agora=VISITA,
        )
        await session.commit()
        atual = remarcado.novo_id

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_criados == 1
    assert indicadores.agendamentos_confirmados == 1


async def test_expirado_nao_e_visita_marcada(session) -> None:
    """D5: a reserva atropelada ou recusada nunca virou compromisso.

    Conta-la diria que o agente marcou visita quando o lead disse nao.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    await _agendar(
        session, conversa=CONVERSA, corretor_id=corretor, status=StatusDoAgendamento.EXPIRADO
    )

    indicadores = await _indicadores(session)
    etapas = await contar_etapas(session, recorte=_recorte())

    assert indicadores.agendamentos_criados == 0
    assert etapas[Etapa.AGENDADO] == 0


async def test_cancelado_conta_como_criado(session) -> None:
    """O outro lado da D5: `criados` e sobre ter sido criado.

    Quem marcou e depois cancelou marcou -- a diferenca para o `EXPIRADO` e
    que aquele nunca chegou a ser compromisso.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    await _agendar(
        session, conversa=CONVERSA, corretor_id=corretor, status=StatusDoAgendamento.CANCELADO
    )

    indicadores = await _indicadores(session)
    etapas = await contar_etapas(session, recorte=_recorte())

    assert indicadores.agendamentos_criados == 1
    assert etapas[Etapa.AGENDADO] == 1


async def test_sem_desfecho_decidido_a_taxa_e_nula_e_nao_zero(session) -> None:
    """D6: `CONFIRMADO` vencido que ninguem marcou nao decidiu nada.

    Zero afirmaria que ninguem faltou; nulo diz que nao ha o que medir. E a
    forma em que o indicador vai sair ate a TEC-374 ligar as duas transicoes.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    await _agendar(session, conversa=CONVERSA, corretor_id=corretor)

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_criados == 1
    assert indicadores.agendamentos_realizados == 0
    assert indicadores.taxa_no_show is None


async def test_o_recorte_e_de_coorte_e_nao_de_atividade(session) -> None:
    """D2: agendamento de lead nascido FORA do periodo nao conta.

    O recorte e o mesmo dos outros seis indicadores -- misturar coorte com
    atividade poria dois denominadores diferentes com a mesma aparencia.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    await _lead(session, conversa="5511900000002", nasceu_em=FORA)
    await _agendar(session, conversa=CONVERSA, corretor_id=corretor)
    await _agendar(
        session,
        conversa="5511900000002",
        corretor_id=corretor,
        inicio=VISITA + timedelta(days=1),
    )

    indicadores = await _indicadores(session)

    assert indicadores.agendamentos_criados == 1


async def test_um_lead_com_duas_visitas_soma_duas_e_conta_uma_etapa(session) -> None:
    """D3: as duas unidades da mesma resposta, no mesmo cenario.

    O indicador conta COMPROMISSOS e a etapa conta LEADS. Sem esta asserta,
    quem lesse as duas consultas presumindo a mesma unidade concluiria que uma
    delas esta errada.
    """
    corretor = await _corretor(session)
    await _lead(session, conversa=CONVERSA, nasceu_em=DENTRO)
    for dia in (0, 1):
        await _agendar(
            session,
            conversa=CONVERSA,
            corretor_id=corretor,
            inicio=VISITA + timedelta(days=dia),
        )

    indicadores = await _indicadores(session)
    etapas = await contar_etapas(session, recorte=_recorte())

    assert indicadores.agendamentos_criados == 2
    assert etapas[Etapa.AGENDADO] == 1
