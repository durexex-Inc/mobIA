"""O lead score deterministico da RN-06.1.

TEC-150. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo -- a
card exige "calculado em codigo, nunca pelo LLM". Os dois fatores que
dependem de dados fora de `LeadQualification` entram por parametro, e nao por
consulta aqui dentro: quem chama consulta, e a regra continua testavel sem
banco. Mesma forma que `recusados` tem em `esta_qualificado`.

**O teto e 95, nao 100**, e 75 enquanto a TEC-158 nao existir. Ver D3 do
desenho: a RN-06.1 da ao fator de completude peso 25 e o criterio "5 pontos
por campo obrigatorio", e a RN-05.3 lista quatro obrigatorios. As duas
afirmacoes nao fecham, e vale a regra operavel.
"""

from dataclasses import dataclass

from mobia.domain.agente.schemas import FormaPagamento, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import campos_obrigatorios_preenchidos

PONTOS_POR_CAMPO_OBRIGATORIO = 5

# Constantes de modulo, e nao configuracao. A card pede pesos alteraveis sem
# deploy e a CA-19.1 pede sem reiniciar a aplicacao -- isso e um subsistema
# (persistir, autorizar, invalidar cache) e pertence ao epico de configuracao,
# nao ao de scoring. Lacuna declarada no desenho.
_PONTOS_POR_URGENCIA = {
    Urgencia.IMEDIATA.value: 25,
    Urgencia.ATE_3_MESES.value: 15,
    Urgencia.ATE_6_MESES.value: 8,
    Urgencia.SEM_PRESSA.value: 0,
}

# A RN-06.1 pontua tres categorias -- a vista, financiamento pre-aprovado, a
# avaliar -- e o enum tem cinco valores.
#
# Pre-aprovacao nao existe como dado neste repo, entao FINANCIAMENTO recebe os
# 12 do pre-aprovado: quem menciona financiar pontua como quem tem carta. E
# generoso, e esta declarado.
#
# CONSORCIO e FGTS nao tem nota no SRS. Recebem 12 por serem, como o
# financiamento, caminho de pagamento definido e nao "a avaliar". Inventar
# hierarquia mais fina entre os tres seria criar regra que o SRS nao contem.
_PONTOS_POR_CAPACIDADE = {
    FormaPagamento.A_VISTA.value: 15,
    FormaPagamento.FINANCIAMENTO.value: 12,
    FormaPagamento.CONSORCIO.value: 12,
    FormaPagamento.FGTS.value: 12,
    FormaPagamento.INDEFINIDA.value: 6,
}

# Coluna nula significa o mesmo que INDEFINIDA aqui: o lead nao disse como
# pagaria, e isso e "a avaliar", nao ausencia de capacidade.
_PONTOS_SEM_FORMA_DE_PAGAMENTO = 6


@dataclass(frozen=True)
class Score:
    """O score e a contribuicao de cada fator.

    A card exige que "cada fator devolve sua contribuicao, nao so o total":
    a TEC-152 grava "score anterior, novo, fatores e timestamp", e uma
    auditoria que precisasse recalcular os fatores para audita-los nao
    auditaria nada.
    """

    completude: int
    urgencia: int
    catalogo: int
    engajamento: int
    capacidade: int

    @property
    def total(self) -> int:
        return self.completude + self.urgencia + self.catalogo + self.engajamento + self.capacidade


def calcular_score(
    estado: LeadQualification | None,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
) -> Score:
    """O score da RN-06.1. Nunca levanta.

    `imoveis_compativeis` tem default zero porque a busca de imoveis
    (TEC-158) nao existe, e a card prescreve que ate la o fator contribua
    zero. Quando ela existir, o chamador passa o numero real e nenhuma linha
    daqui muda.
    """
    if estado is None:
        return Score(completude=0, urgencia=0, catalogo=0, engajamento=0, capacidade=0)

    return Score(
        completude=campos_obrigatorios_preenchidos(estado) * PONTOS_POR_CAMPO_OBRIGATORIO,
        urgencia=_PONTOS_POR_URGENCIA.get(estado.urgencia or "", 0),
        catalogo=_pontos_do_catalogo(imoveis_compativeis),
        engajamento=_pontos_do_engajamento(mensagens_do_lead),
        capacidade=_PONTOS_POR_CAPACIDADE.get(
            estado.forma_pagamento or "", _PONTOS_SEM_FORMA_DE_PAGAMENTO
        ),
    )


def _pontos_do_catalogo(imoveis: int) -> int:
    if imoveis >= 5:
        return 20
    return 12 if imoveis >= 1 else 0


def _pontos_do_engajamento(mensagens: int) -> int:
    """Faixas arbitradas, e o criterio de aceite foi o unico guia.

    A RN-06.1 diz apenas "por numero de mensagens do lead e tempo medio de
    resposta" -- e o unico dos cinco fatores sem faixas. O cenario de aceite
    pede >=70 para um lead com os quatro obrigatorios, prazo de 20 dias e
    pagamento a vista: isso soma 60 sem catalogo, entao engajamento precisa
    render >=10 para o criterio da propria card fechar. Um lead que informou
    quatro campos mandou, por construcao, ao menos tres mensagens.

    Tempo medio de resposta fica fora, declarado como lacuna no desenho.
    """
    if mensagens >= 6:
        return 15
    if mensagens >= 3:
        return 10
    return 5 if mensagens >= 1 else 0
