"""Qual corretor atende o lead num dado dia. TEC-166, RN-11.2, RN-07.4.

Puro: nao toca banco, rede nem relogio. A contagem de visitas do dia entra
pronta, e quem percorre as datas e `janelas_alocadas` (`janelas.py`). Ver
docs/superpowers/specs/2026-09-24-tec-166-alocar-corretor-design.md.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mobia.domain.agendamento.vocabulario import MotivoDaAlocacao
from mobia.domain.agente.schemas import normalizar_regiao
from mobia.domain.catalogo.busca import zonas_de
from mobia.domain.context.models import LeadQualification
from mobia.domain.corretores.models import Corretor
from mobia.domain.corretores.vocabulario import Especialidade, especialidade_de


@dataclass(frozen=True)
class CriterioDoLead:
    especialidade: Especialidade | None
    regiao: str | None


# COMPRA e ALUGUEL sao grafadas identicas em `Intencao` e em `Especialidade`
# (D3 da TEC-196): a traducao e por igualdade de string.
_POR_IGUALDADE = (Especialidade.COMPRA, Especialidade.ALUGUEL)


def criterio_de(qualificacao: LeadQualification) -> CriterioDoLead:
    """O que a alocacao precisa saber do lead. D1 do desenho.

    Investimento sem ticket fica `INVESTIMENTO`: nao ha como afirmar alto
    ticket sem o numero. Intencao que nao e especialidade de ninguem vira
    `None`, e criterio com `None` nunca tem match exato.
    """
    intencao = qualificacao.intencao
    especialidade: Especialidade | None
    if intencao == Especialidade.INVESTIMENTO:
        ticket = qualificacao.ticket_investimento_centavos
        especialidade = Especialidade.INVESTIMENTO if ticket is None else especialidade_de(ticket)
    elif intencao in _POR_IGUALDADE:
        especialidade = Especialidade(intencao)
    else:
        especialidade = None
    return CriterioDoLead(especialidade, qualificacao.regiao or None)


def regiao_casa(do_lead: str, do_corretor: str) -> bool:
    """Igualdade canonica, ou uma zona em comum. D2 do desenho.

    A do corretor foi gravada so com `dobrar()` (D4 da TEC-196); passar as
    duas por `normalizar_regiao` tira "regiao do" e "perto da" dos dois lados.
    **Bairro nao vira zona**: "moema" nao casa "zona sul", porque nao existe
    mapeamento bairro->zona no repo.
    """
    lead, corretor = normalizar_regiao(do_lead), normalizar_regiao(do_corretor)
    if lead == corretor:
        return True
    return bool(set(zonas_de([lead])) & set(zonas_de([corretor])))


@dataclass(frozen=True)
class Alocacao:
    corretor: Corretor
    motivo: MotivoDaAlocacao


def _tem_match(corretor: Corretor, criterio: CriterioDoLead) -> bool:
    # A card pede especialidade E regiao: criterio incompleto nunca casa.
    if criterio.especialidade is None or criterio.regiao is None:
        return False
    if criterio.especialidade not in corretor.especialidades:
        return False
    return any(regiao_casa(criterio.regiao, regiao) for regiao in corretor.regioes_atuacao)


def alocar(
    *,
    criterio: CriterioDoLead,
    corretores: Sequence[Corretor],
    visitas_na_data: Mapping[uuid.UUID, int],
) -> list[Alocacao]:
    """Os candidatos daquela data, em ordem de preferencia. D3 do desenho.

    Primeiro os ativos com match exato e capacidade sobrando; depois os
    plantoes ativos com capacidade que ainda nao estao na lista. Devolve a
    lista, e nao um so, porque quem chama desce para o proximo quando o
    primeiro nao tem horario livre (D5).

    O motivo do plantao depende so de EXISTIR match ativo, esgotado ou nao:
    se o plantao acabou escolhido havendo match, o match nao pode naquele
    dia -- por capacidade aqui, ou por falta de horario em `janelas_alocadas`.

    Desempate por `criado_em` mais antigo, e `id` para a ordem ser total --
    o mesmo criterio de `destinatario_do_handoff`. Balancear carga esta fora
    da card.
    """
    ativos = sorted(
        (corretor for corretor in corretores if corretor.ativo),
        key=lambda corretor: (corretor.criado_em, str(corretor.id)),
    )

    def _cabe(corretor: Corretor) -> bool:
        return visitas_na_data.get(corretor.id, 0) < corretor.capacidade_diaria

    com_match = [corretor for corretor in ativos if _tem_match(corretor, criterio)]
    candidatos = [
        Alocacao(corretor, MotivoDaAlocacao.MATCH_EXATO)
        for corretor in com_match
        if _cabe(corretor)
    ]
    motivo_do_plantao = (
        MotivoDaAlocacao.MATCH_SEM_CAPACIDADE if com_match else MotivoDaAlocacao.SEM_MATCH
    )
    # Plantao que tambem casou ja foi decidido acima -- entrou como match, ou
    # saiu por capacidade. Nao volta pela porta do plantao.
    ja_decididos = {corretor.id for corretor in com_match}
    candidatos += [
        Alocacao(corretor, motivo_do_plantao)
        for corretor in ativos
        if corretor.plantao and corretor.id not in ja_decididos and _cabe(corretor)
    ]
    return candidatos
