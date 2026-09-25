"""Qual corretor atende o lead num dado dia. TEC-166, RN-11.2, RN-07.4.

Puro: nao toca banco, rede nem relogio. A contagem de visitas do dia entra
pronta, e quem percorre as datas e `janelas_alocadas` (`janelas.py`). Ver
docs/superpowers/specs/2026-09-24-tec-166-alocar-corretor-design.md.
"""

from dataclasses import dataclass

from mobia.domain.agente.schemas import normalizar_regiao
from mobia.domain.catalogo.busca import zonas_de
from mobia.domain.context.models import LeadQualification
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
