"""O resumo que o corretor recebe quando o modelo nao entrega. TEC-176.

Modulo sem I/O, como `dossie.py` e `vocabulario.py`: monta texto a partir de
fatos que ja vieram do banco.

**Reusa os MARCADORES do resumo redigido, de proposito.** O corretor le a
mesma estrutura nos dois modos e nao precisa perceber que mudou de formato
para achar o que procura; e um leitor futuro -- o painel da E8, a exportacao
para CRM da TEC-180 -- nao precisa de dois parsers para um campo so. Ver a D3
do desenho.

**Os formatadores de valor vem de `dossie.py`, nao sao reescritos aqui.**
Duas versoes de "ate R$ 600.000" seriam duas fontes para o mesmo fato -- o
defeito que a TEC-146 gastou uma card inteira consertando.
"""

from mobia.domain.handoff.dossie import (
    Dossie,
    faixa,
    fatores,
    forcada_por,
    imoveis,
    isoformat_ou_none,
    ou_ausente,
    pontos_de_atencao,
    sim_nao,
)
from mobia.domain.handoff.resumo import MARCADORES, validar

# A linha que identifica o modo. Fica no TOPO do texto (nao junto do bloco de
# proxima acao): e o "fica indicado que se trata de resumo automatico
# simplificado" do segundo cenario do Gherkin, e quem le precisa saber disso
# antes de ler qualquer fato, nao depois.
TEXTO_DE_CONTINGENCIA = (
    "[resumo automatico simplificado -- o modelo de linguagem nao gerou o "
    "resumo desta vez; o texto abaixo foi montado direto dos dados "
    "registrados, sem redacao]"
)

# Teto da lista de "## Imoveis apresentados" e teto de cada lista do bloco
# "## Pontos de atencao" (`campos_recusados` e `perguntados_sem_resposta`).
#
# Os dois foram medidos JUNTOS, e nao um de cada vez: um primeiro corte so
# stressando `imoveis` (a task original) achou TETO_DE_IMOVEIS = 7 sozinho,
# mas a revisao da Task 1 apontou que `campos_recusados` e
# `perguntados_sem_resposta` sao `ARRAY(String(32))` sem cardinalidade
# maxima -- ver `context/models.py` --, e sem corte elas estouravam os 1.500
# do mesmo jeito que a lista de imoveis estourava antes de ganhar teto.
# `motivo_descarte` nao entra nessa conta: vem de `CategoriaDescarte`, um
# enum pequeno, entao a lista deduplicada em `pontos_de_atencao` ja e curta
# sozinha, corte ou nao.
#
# Pior caso medido: 40 imoveis com a linha mais longa que `imoveis()`
# escreve (reacao "DESCARTOU", motivo "PRECO"), mais `campos_recusados` e
# `perguntados_sem_resposta` com 50 itens de 32 caracteres cada -- o maximo
# que a coluna aceita por item --, mais regiao, score_fatores e motivos de
# temperatura forcada no maior tamanho plausivel. Variando os dois tetos
# juntos (`len(contingencia.montar(pior_caso))`, com os modulos reais):
#
#   imoveis=7 lista=1 -> 1498   imoveis=6 lista=1 -> 1442
#   imoveis=5 lista=1 -> 1386   imoveis=5 lista=2 -> 1454
#   imoveis=4 lista=2 -> 1398   imoveis=4 lista=3 -> 1466
#
# `imoveis=7, lista=1` cabe, mas com 2 caracteres de folga -- frouxo demais
# para sobreviver a qualquer ajuste futuro de texto. `imoveis=5, lista=2` da
# 46 caracteres de folga (1454) e mostra pelo menos dois itens em cada lista
# de atencao, em vez de um so; foi a escolha, trocando dois imoveis visiveis
# por uma folga que nao desaparece no primeiro commit seguinte.
TETO_DE_IMOVEIS = 5
TETO_POR_LISTA_DE_ATENCAO = 2


def montar(dossie: Dossie) -> str:
    """Os seis blocos da RN-15.1, montados so de fatos que ja vieram do banco.

    Sem chamada de modelo, sem redacao: quando o resumo redigido falha (D7),
    isto e o que sobra para o corretor, e por isso nao pode falhar por sua
    vez. `validar()` e o mesmo dos dois modos -- ver o cabecalho do modulo.
    """
    forcada = forcada_por(dossie)
    texto = "\n".join(
        (
            TEXTO_DE_CONTINGENCIA,
            "",
            MARCADORES[0],
            f"canal: {dossie.canal}",
            f"conversa: {dossie.conversa}",
            f"primeira mensagem: {ou_ausente(isoformat_ou_none(dossie.primeira_mensagem_em))}",
            f"mensagens do lead: {dossie.mensagens_do_lead}",
            "",
            MARCADORES[1],
            f"intencao: {ou_ausente(dossie.intencao)}",
            f"faixa de preco: {faixa(dossie)}",
            f"regiao: {ou_ausente(dossie.regiao)}",
            f"tipo de imovel: {ou_ausente(dossie.tipo_imovel)}",
            f"quartos: {ou_ausente(dossie.quartos)}",
            f"vagas: {ou_ausente(dossie.vagas)}",
            f"urgencia: {ou_ausente(dossie.urgencia)}",
            f"forma de pagamento: {ou_ausente(dossie.forma_pagamento)}",
            f"tem imovel para vender: {sim_nao(dossie.tem_imovel_para_vender)}",
            "",
            MARCADORES[2],
            f"score total: {ou_ausente(dossie.score_total)}",
            f"fatores: {fatores(dossie)}",
            f"temperatura: {ou_ausente(dossie.temperatura)}{forcada}",
            "",
            MARCADORES[3],
            imoveis(dossie, teto=TETO_DE_IMOVEIS),
            "",
            MARCADORES[4],
            pontos_de_atencao(dossie, teto=TETO_POR_LISTA_DE_ATENCAO),
            "",
            # Apresenta FATOS -- gatilho, etiqueta, prioridade --, nunca uma
            # recomendacao. Recomendar e julgamento, e e o que o resumo
            # redigido pelo modelo fazia; o quarto cenario do Gherkin proibe
            # objecao ou proxima acao inventada aqui.
            MARCADORES[5],
            f"gatilho: {dossie.gatilho}",
            f"etiqueta: {dossie.etiqueta}",
            f"prioridade: {dossie.prioridade}",
        )
    )
    return validar(texto)
