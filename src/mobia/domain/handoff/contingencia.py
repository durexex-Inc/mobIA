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

from mobia.domain.agente.schemas import (
    CategoriaDescarte,
    FormaPagamento,
    Intencao,
    TipoImovel,
    Urgencia,
)
from mobia.domain.handoff.dossie import (
    Dossie,
    imoveis,
    linha_canal,
    linha_etiqueta,
    linha_fatores,
    linha_gatilho,
    linha_mensagens_do_lead,
    linha_primeira_mensagem,
    linha_prioridade,
    linha_temperatura,
    linhas_de_criterios,
    ou_ausente,
    pontos_de_atencao,
    truncado,
)
from mobia.domain.handoff.resumo import MARCADORES, validar
from mobia.domain.handoff.vocabulario import ETIQUETA_DE, Gatilho

# A linha que identifica o modo. Fica no TOPO do texto (nao junto do bloco de
# proxima acao): e o "fica indicado que se trata de resumo automatico
# simplificado" do segundo cenario do Gherkin, e quem le precisa saber disso
# antes de ler qualquer fato, nao depois.
TEXTO_DE_CONTINGENCIA = (
    "[resumo automatico simplificado -- o modelo de linguagem nao gerou o "
    "resumo desta vez; o texto abaixo foi montado direto dos dados "
    "registrados, sem redacao]"
)

# Teto de cada campo de VALOR UNICO que entra no template -- revisao final da
# TEC-176 (Critical 1a). Ate aqui so as LISTAS (`imoveis`, `campos_recusados`,
# `perguntados_sem_resposta`) tinham teto; um campo como `regiao` ia para o
# texto do tamanho que viesse do banco, sem corte nenhum. `Dossie` e um
# dataclass sem validacao de tamanho, e `regiao` e `String(120)`
# (`context/models.py`) -- um dossie real, dentro do que o banco aceita,
# conseguia estourar os 1.500 da RN-15.2 sozinho por essa lacuna: o pior caso
# do teste original usava `regiao` com 47 de 120, e o mesmo teste com
# `regiao` no MAXIMO da coluna dava 1521 (estoura). Ver o relatorio da Task 3
# para as tres medicoes que expuseram isto.
#
# Cada numero abaixo vem do maior valor REAL que o campo pode assumir:
#   - quando o campo e alimentado por um enum FECHADO (`Intencao`,
#     `TipoImovel`, `Urgencia`, `FormaPagamento`, `Gatilho`, `ETIQUETA_DE`,
#     `CategoriaDescarte`), o teto e o comprimento do maior MEMBRO do enum,
#     computado abaixo e nao copiado a mao -- a coluna do banco e sempre mais
#     larga (ela precisa cobrir qualquer enum futuro maior), e usar o
#     tamanho da coluna gastaria orcamento que a aplicacao nunca escreve;
#   - quando o campo e texto livre de verdade (sem enum fechado por tras --
#     `regiao`, `canal`, `conversa`, `codigo`), o teto e o tamanho da COLUNA
#     (`context/models.py`, `handoff/models.py`, `catalogo/models.py`).
TETO_INTENCAO = max(len(m.value) for m in Intencao)  # SUPORTE_CONTRATO (16)
TETO_TIPO_IMOVEL = max(len(m.value) for m in TipoImovel)  # APARTAMENTO (11)
TETO_URGENCIA = max(len(m.value) for m in Urgencia)  # ATE_3_MESES / ATE_6_MESES (11)
TETO_FORMA_PAGAMENTO = max(len(m.value) for m in FormaPagamento)  # FINANCIAMENTO (13)
TETO_GATILHO = max(len(m.value) for m in Gatilho)  # AGENDAMENTO_CONFIRMADO (22)
TETO_ETIQUETA = max(len(v) for v in ETIQUETA_DE.values())  # agendamento-confirmado (22)
# `motivo_descarte` (`Recomendacao.motivo_descarte`, `agente/models.py`) e
# `String(80)` mas so recebe uma `CategoriaDescarte` (ver o docstring da
# coluna) -- por isso o teto usa o enum, e nao os 80 da coluna.
TETO_MOTIVO_DESCARTE = max(len(m.value) for m in CategoriaDescarte)  # DISTANCIA (9)
TETO_REGIAO = 120  # LeadQualification.regiao, context/models.py -- texto livre de verdade
TETO_CANAL = 32  # Handoff.channel, handoff/models.py -- texto livre, sem enum fechado
TETO_CONVERSA = 64  # Handoff.conversation_key, handoff/models.py -- texto livre
TETO_CODIGO = 20  # Imovel.codigo, catalogo/models.py -- texto livre

# Teto da lista de "## Imoveis apresentados" e teto de cada lista do bloco
# "## Pontos de atencao" (`campos_recusados` e `perguntados_sem_resposta`).
#
# Os dois foram medidos JUNTOS, e nao um de cada vez: um primeiro corte so
# stressando `imoveis` (a task original) achou TETO_DE_IMOVEIS = 7 sozinho,
# e a revisao da Task 1 achou TETO_DE_IMOVEIS = 5 / TETO_POR_LISTA_DE_ATENCAO
# = 2 depois de considerar `campos_recusados` e `perguntados_sem_resposta`
# (`ARRAY(String(32))` sem cardinalidade maxima). Nenhuma das duas rodadas
# testou TODOS os campos de valor unico no maximo que a coluna aceita ao
# mesmo tempo -- so `regiao` variava --, e e exatamente essa lacuna que o
# Critical da revisao final encontrou: com regiao=120 (nao 47) o mesmo
# dossie da Task 1 ja estourava (1521), e um dossie combinando regiao=98 com
# 20 imoveis descartados estourava mais ainda (1607).
#
# Pior caso medido agora com `contingencia.montar` de verdade, TODOS os
# campos de valor unico no teto que a tabela acima define, 40 imoveis (cada
# um com `codigo`, `reacao` e `motivo_descarte` no maior tamanho real que o
# campo assume), e 50 itens de 32 caracteres em cada lista de atencao -- o
# maximo que `ARRAY(String(32))` aceita por item:
#
#   imoveis=5 lista=2 -> estoura (1751 de 1500)
#   imoveis=5 lista=1 -> estoura (1683 de 1500)
#   imoveis=3 lista=2 -> estoura (1597 de 1500)
#   imoveis=3 lista=1 -> estoura (1529 de 1500)
#   imoveis=2 lista=2 -> estoura (1520 de 1500)
#   imoveis=2 lista=1 -> 1452 (48 de folga)
#   imoveis=1 lista=2 -> 1443 (57 de folga)
#   imoveis=1 lista=1 -> 1375 (125 de folga)
#
# `imoveis=5, lista=2` -- os valores da Task 1 -- estoura por 251
# caracteres assim que todo campo de valor unico entra na conta, nao so
# `regiao`. `imoveis=2, lista=1` cabe com 48 caracteres de folga -- a MESMA
# ordem de grandeza que a Task 1 ja tinha aceitado como suficiente
# (`imoveis=5 lista=2 -> 1454`, 46 de folga, na medicao antiga, que so
# variava `regiao`); manter o mesmo patamar aqui, e nao encolher mais so por
# encolher, e a mesma troca que a Task 1 fez: dois imoveis visiveis (em vez
# de cinco) e um item por lista de atencao (em vez de dois), por uma folga
# que sobrevive ao proximo ajuste de texto.
TETO_DE_IMOVEIS = 2
TETO_POR_LISTA_DE_ATENCAO = 1


def montar(dossie: Dossie) -> str:
    """Os seis blocos da RN-15.1, montados so de fatos que ja vieram do banco.

    Sem chamada de modelo, sem redacao: quando o resumo redigido falha (D7),
    isto e o que sobra para o corretor, e por isso nao pode falhar por sua
    vez. `validar()` e o mesmo dos dois modos -- ver o cabecalho do modulo.

    **Todo campo de texto livre entra com teto** (revisao final, Critical
    1a): antes, so as listas cortavam; um valor unico como `regiao` no
    maximo que a coluna aceita, somado ao resto do dossie tambem no maximo,
    estourava os 1.500 da RN-15.2 e fazia `validar()` levantar -- e essa
    excecao saia de `gerar_resumo` sem guarda nenhuma (ver o Critical da
    revisao e a rede de seguranca em `geracao.gerar_resumo`). Este teto
    garante que NENHUMA entrada que o banco consiga produzir passa disso;
    ver a tabela de medicao acima de `TETO_DE_IMOVEIS`.
    """
    texto = "\n".join(
        (
            TEXTO_DE_CONTINGENCIA,
            "",
            MARCADORES[0],
            linha_canal(dossie, TETO_CANAL),
            f"conversa: {truncado(dossie.conversa, TETO_CONVERSA)}",
            linha_primeira_mensagem(dossie),
            linha_mensagens_do_lead(dossie),
            "",
            MARCADORES[1],
            *linhas_de_criterios(
                dossie,
                {
                    "intencao": TETO_INTENCAO,
                    "regiao": TETO_REGIAO,
                    "tipo_imovel": TETO_TIPO_IMOVEL,
                    "urgencia": TETO_URGENCIA,
                    "forma_pagamento": TETO_FORMA_PAGAMENTO,
                },
            ),
            "",
            MARCADORES[2],
            f"score total: {ou_ausente(dossie.score_total)}",
            linha_fatores(dossie),
            linha_temperatura(dossie),
            "",
            MARCADORES[3],
            imoveis(
                dossie,
                teto=TETO_DE_IMOVEIS,
                teto_codigo=TETO_CODIGO,
                teto_motivo_descarte=TETO_MOTIVO_DESCARTE,
            ),
            "",
            MARCADORES[4],
            pontos_de_atencao(
                dossie, teto=TETO_POR_LISTA_DE_ATENCAO, teto_motivo_descarte=TETO_MOTIVO_DESCARTE
            ),
            "",
            # Apresenta FATOS -- gatilho, etiqueta, prioridade --, nunca uma
            # recomendacao. Recomendar e julgamento, e e o que o resumo
            # redigido pelo modelo fazia; o quarto cenario do Gherkin proibe
            # objecao ou proxima acao inventada aqui.
            MARCADORES[5],
            linha_gatilho(dossie, TETO_GATILHO),
            linha_etiqueta(dossie, TETO_ETIQUETA),
            linha_prioridade(dossie),
        )
    )
    return validar(texto)
