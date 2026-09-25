"""Janelas com corretor alocado, uma por dia. TEC-166, D5 do desenho.

25/08/2026 e uma terca-feira; a janela da imobiliaria fica nos valores padrao
de `Settings` (segunda a sabado, 9h as 19h). A jornada dos corretores e 9h-18h.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from mobia.domain.agendamento.alocacao import CriterioDoLead
from mobia.domain.agendamento.janelas import (
    Intervalo,
    JanelaAlocada,
    TipoDeCompromisso,
    janelas_alocadas,
)
from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.vocabulario import Especialidade

SP = ZoneInfo("America/Sao_Paulo")
COMPRA_SUL = CriterioDoLead(Especialidade.COMPRA, "zona sul")
VISITA = TipoDeCompromisso.VISITA_PRESENCIAL


def _ago(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=SP)


def _hora(inicio: datetime, minutos: int = 60) -> Intervalo:
    return Intervalo(inicio, inicio + timedelta(minutes=minutos))


def _corretor(nome: str, *, plantao: bool = False, capacidade: int = 1, ordem: int = 0) -> Corretor:
    return Corretor(
        id=uuid.uuid4(),
        nome=nome,
        especialidades=["COMPRA"],
        regioes_atuacao=["norte"] if plantao else ["zona sul"],
        plantao=plantao,
        ativo=True,
        capacidade_diaria=capacidade,
        horario_inicio=9,
        horario_fim=18,
        criado_em=datetime(2026, 1, 1 + ordem, tzinfo=UTC),
    )


class _AgendaPorCorretor:
    def __init__(self, ocupados: dict[uuid.UUID, list[Intervalo]] | None = None) -> None:
        self._ocupados = ocupados or {}

    async def ocupados(
        self, corretor_id: uuid.UUID, de: datetime, ate: datetime
    ) -> list[Intervalo]:
        return self._ocupados.get(corretor_id, [])


class _ContadorFalso:
    def __init__(self, visitas: dict[tuple[uuid.UUID, date], int] | None = None) -> None:
        self._visitas = visitas or {}
        self.chamadas: list[tuple[list[uuid.UUID], date, date, datetime]] = []

    async def visitas_por_dia(
        self, corretor_ids: Sequence[uuid.UUID], *, de: date, ate: date, agora: datetime
    ) -> dict[tuple[uuid.UUID, date], int]:
        self.chamadas.append((list(corretor_ids), de, ate, agora))
        return self._visitas


async def _alocar(corretores, *, agenda=None, visitas=None, tipo=VISITA, ate=None):
    return await janelas_alocadas(
        criterio=COMPRA_SUL,
        corretores=corretores,
        agenda=agenda or _AgendaPorCorretor(),
        visitas=visitas or _ContadorFalso(),
        agora=_ago(25, 14),
        ate=ate or _ago(29, 19),
        tipo=tipo,
    )


async def test_quinta_esgotada_vai_para_o_proximo_candidato() -> None:
    ana = _corretor("ana")
    plantao = _corretor("plantao", plantao=True, ordem=1)
    visitas = _ContadorFalso({(ana.id, date(2026, 8, 27)): 1})
    resultado = await _alocar([ana, plantao], visitas=visitas)
    assert resultado == [
        JanelaAlocada(_hora(_ago(25, 17)), ana.id, MotivoDaAlocacao.MATCH_EXATO),
        JanelaAlocada(_hora(_ago(26, 9)), ana.id, MotivoDaAlocacao.MATCH_EXATO),
        JanelaAlocada(_hora(_ago(27, 9)), plantao.id, MotivoDaAlocacao.MATCH_SEM_CAPACIDADE),
    ]


async def test_match_sem_horario_livre_cai_no_plantao() -> None:
    ana = _corretor("ana", capacidade=5)
    plantao = _corretor("plantao", plantao=True, ordem=1)
    # Terca: a unica janela depois das 3h de antecedencia e 17h-18h.
    agenda = _AgendaPorCorretor({ana.id: [_hora(_ago(25, 17))]})
    resultado = await _alocar([ana, plantao], agenda=agenda)
    assert resultado[0] == JanelaAlocada(
        _hora(_ago(25, 17)), plantao.id, MotivoDaAlocacao.MATCH_SEM_CAPACIDADE
    )
    assert resultado[1].corretor_id == ana.id


async def test_contador_recebe_as_datas_locais_inteiras_e_o_agora() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso()
    await _alocar([ana], visitas=visitas)
    assert visitas.chamadas == [([ana.id], date(2026, 8, 25), date(2026, 8, 29), _ago(25, 14))]


async def test_reuniao_remota_ignora_a_capacidade() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso({(ana.id, date(2026, 8, dia)): 9 for dia in range(25, 30)})
    resultado = await _alocar([ana], visitas=visitas, tipo=TipoDeCompromisso.REUNIAO_REMOTA)
    assert visitas.chamadas == []
    assert [j.corretor_id for j in resultado] == [ana.id, ana.id, ana.id]


async def test_no_maximo_tres_uma_por_dia() -> None:
    ana = _corretor("ana", capacidade=5)
    resultado = await _alocar([ana], ate=_sp_setembro(5))
    dias = [j.janela.inicio.astimezone(SP).date() for j in resultado]
    assert len(resultado) == 3
    assert len(set(dias)) == 3


async def test_ninguem_pode_da_lista_vazia() -> None:
    ana = _corretor("ana")
    visitas = _ContadorFalso({(ana.id, date(2026, 8, dia)): 1 for dia in range(25, 30)})
    assert await _alocar([ana], visitas=visitas) == []


def _sp_setembro(dia: int) -> datetime:
    return datetime(2026, 9, dia, 19, tzinfo=SP)
