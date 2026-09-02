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
#
# **Consequencia: o piso real de qualquer lead com linha e 6, e nao 0.** So
# `estado is None` -- lead sem nenhuma linha em `LeadQualification` -- zera os
# cinco fatores. Os dois casos significam "nunca disse como pagaria" e pontuam
# diferente de proposito: sem linha nao ha lead a ordenar na fila, e o zero e
# a ausencia de sujeito, nao uma nota sobre ele.
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
    *,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
) -> Score:
    """O score da RN-06.1. Nunca levanta.

    **As duas contagens sao keyword-only de proposito.** Sao dois `int`
    adjacentes com o mesmo default: trocar a ordem nao levanta, nao produz
    erro de tipo, nao e visivel ao mypy, e devolve score errado em silencio.
    O primeiro chamador (TEC-151) esta sendo escrito agora, e o custo de
    fechar isso antes dele e um token.

    **`mensagens_do_lead` conta as falas de ENTRADA do lead que a moderacao
    nao bloqueou.** Concretamente: as linhas de `messages` com
    `direction == INBOUND` (equivalentemente `role == LEAD`, que a ingestao
    grava no mesmo INSERT) e `bloqueada_em IS NULL`. Tres leituras eram
    defensaveis e esta e a escolhida, pelos motivos abaixo -- quem for
    escrever a consulta na TEC-151 e na TEC-152 tem de escrever a mesma, e
    duas fontes para o mesmo fato divergiriam em silencio, que e o defeito
    que a TEC-146 gastou uma card inteira consertando.

      - **Nao e a conversa inteira.** Fala do agente nao e engajamento do
        lead, e contar as duas direcoes quase dobra o numero e empurra MORNO
        para QUENTE de graca.
      - **Fala bloqueada nao conta.** Nao e criterio novo: `literais_apos`
        (`context/janela.py`) ja filtra `bloqueada_em IS NULL` desde a
        TEC-236, que tirou a fala bloqueada do contexto e do resumo. Um turno
        que o resto do produto trata como nao-dito nao pode virar ponto aqui.
      - **`status` nao entra.** RECEIVED, QUEUED e PROCESSED descrevem o
        pipeline de ingestao, nao se o lead falou. Filtrar por status faria a
        contagem oscilar com retentativa.

    **Este score nao sabe se o lead esta qualificado.** Nenhum dos cinco
    fatores consulta `esta_qualificado`, e completude conta campos, nao a
    decisao. Um lead com `intencao=VENDER_IMOVEL` -- que a RN-03.4 manda
    direto para handoff e o SDR nao qualifica --, resto preenchido, urgencia
    `IMEDIATA`, pagamento a vista e seis mensagens soma **70**, faixa QUENTE,
    com `esta_qualificado` False; um lead qualificado que so nao disse como
    pagaria soma **66**, faixa MORNO. **Quem ordenar a fila (TEC-151) tem de
    combinar o total com `esta_qualificado`, e nunca usar o total sozinho.**
    Lacuna declarada no desenho.

    **O engajamento nao decai.** Nao ha janela de recencia: oito mensagens de
    quatro meses atras valem 15 para sempre, duas de hoje valem 10, e o score
    de um lead e monotono nao-decrescente ao longo da vida da conversa. Onde
    o recalculo vive e decisao da TEC-151/TEC-152, mas a forma do fator e
    decidida aqui, e por isso a lacuna e desta card.

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
    """Tres faixas arbitradas, e o criterio de aceite foi o unico guia.

    A RN-06.1 diz apenas "por numero de mensagens do lead e tempo medio de
    resposta" -- e o unico dos cinco fatores sem faixas. O cenario de aceite
    pede >=70 para um lead com os quatro obrigatorios, prazo de 20 dias e
    pagamento a vista: isso soma 60 sem catalogo, entao engajamento precisa
    render >=10 para o criterio da propria card fechar.

    **Falar vale 10; falar muito vale 15. A faixa de baixo comeca em UMA
    mensagem.** Nao ha faixa intermediaria, e nao ha faixa de 5 pontos,
    porque o lead pode informar tudo num turno so: `Extracao` carrega
    `faixa_preco`, `regiao`, `urgencia` e `forma_pagamento` de uma vez, e a
    `intencao` sai do classificador do mesmo turno. O corpus tem o caso --
    `borda-injecao-01`, turno 2, em `evals/corpus/borda.yaml`, uma unica fala
    que traz regiao, faixa de preco e forma de pagamento. Com uma faixa de 5
    pontos abaixo de tres mensagens, esse lead somava 65 e reprovava o
    criterio de aceite da propria card.

    Tres faixas em vez de quatro tambem limitam o que a verbosidade sozinha
    decide: entre um lead de uma mensagem e um de seis ha 5 pontos, e nao 10.
    Com 10, o comprador conciso a vista ranqueava abaixo do lead tagarela que
    so mencionou financiamento, e o comprimento da conversa pesava mais que
    um campo obrigatorio faltando.

    Tempo medio de resposta fica fora, e o fator nao decai com o tempo: as
    duas lacunas estao declaradas no desenho, e a segunda tambem na docstring
    de `calcular_score`.
    """
    if mensagens >= 6:
        return 15
    return 10 if mensagens >= 1 else 0
