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
from mobia.domain.handoff.resumo import LIMITE_DE_CARACTERES, MARCADORES, validar
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

# Teto de cada lista do bloco "## Pontos de atencao" (`campos_recusados` e
# `perguntados_sem_resposta`, `ARRAY(String(32))` sem cardinalidade maxima).
#
# **A lista de imoveis NAO tem teto desde a TEC-276** -- ela usa o orcamento
# que sobra, ver `montar`. Ate ali havia um `TETO_DE_IMOVEIS = 2` fixo,
# dimensionado para o pior caso do banco, e uma tabela de folgas de 20 linhas
# neste comentario justificando o numero. A tabela saiu por nao ser
# reproduzivel: tres pessoas a re-derivaram e acharam tres resultados
# diferentes (1452, e depois 1425, com um ponto de fronteira discordando de
# sentido), e nenhum deles sobreviveria a uma palavra acrescentada a um bloco.
# Quem quiser o numero de hoje roda
# `tests/unit/test_handoff_contingencia.py` -- a medicao vive la, derivada
# dos `TETO_*` acima, e nao aqui em prosa.
#
# **Estas duas listas continuam com teto fixo, e e lacuna declarada.** Dar a
# elas o orcamento que sobra exigiria decidir se o corretor prefere ver um
# imovel a mais ou um campo recusado a mais -- decisao de produto, nao de
# codigo (D2 do desenho da TEC-276). No lead tipico sobram ~80 caracteres
# depois dos imoveis.
TETO_POR_LISTA_DE_ATENCAO = 1


def _texto_com(dossie: Dossie, quantos_imoveis: int) -> str:
    """Os seis blocos da RN-15.1 com `quantos_imoveis` na lista de imoveis.

    Nao valida: quem chama e `montar`, que monta varias vezes ate achar o
    maior `quantos_imoveis` que cabe, e so entao valida uma vez. Validar
    aqui faria a busca usar excecao como fluxo de controle.

    **Todo campo de texto livre entra com teto** (TEC-176, revisao final,
    Critical 1a): antes, so as listas cortavam; um valor unico como `regiao`
    no maximo que a coluna aceita, somado ao resto do dossie tambem no
    maximo, estourava os 1.500 da RN-15.2 e fazia `validar()` levantar -- e
    essa excecao saia de `gerar_resumo` sem guarda nenhuma. Os tetos de
    campo continuam necessarios depois da TEC-276: o orcamento decide
    QUANTOS imoveis entram, nao o tamanho de cada campo.
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
                teto=quantos_imoveis,
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
    return texto


def montar(dossie: Dossie) -> str:
    """O resumo de contingencia com tantos imoveis quantos couberem. TEC-276.

    Sem chamada de modelo, sem redacao: quando o resumo redigido falha (D7),
    isto e o que sobra para o corretor, e por isso nao pode falhar por sua
    vez. `validar()` e o mesmo dos dois modos -- ver o cabecalho do modulo.

    **"Cabe por construcao" passou a ser propriedade do algoritmo, e nao de
    uma tabela.** Ate a TEC-276 a lista tinha teto fixo de 2, escolhido a
    partir de um pior caso medido a mao e escrito em comentario: a garantia
    valia enquanto aquela medicao valesse, e ela morreria em silencio no dia
    em que alguem acrescentasse uma palavra a um marcador. Agora o texto que
    sai foi MEDIDO antes de sair, qualquer que seja o texto dos blocos.

    O preco que se pagava era do corretor: no lead tipico o resumo usava 923
    dos 1.500 caracteres para mostrar 2 imoveis de trinta -- 577 caracteres
    de contexto deixados na mesa justamente no modo que so entra no dia
    ruim. Hoje o mesmo lead ve 17 (medido pelo caminho novo, nao estimado),
    e o pior caso do banco degrada sozinho
    para 2, sem ninguem dimensionar nada.

    **Sobe do zero em vez de descer do topo, e a razao e medida.** Cada
    imovel a mais so ACRESCENTA caracteres, entao a busca e monotona e pode
    parar no primeiro que estoura. Subindo, o numero de montagens e limitado
    pelo orcamento -- uma linha de imovel nao tem menos de ~30 caracteres,
    logo nunca ha mais de ~40 candidatas. Descendo, ele seria limitado pelo
    DOSSIE: um de 200 imoveis gastaria ~17 ms em candidatas que estouram, a
    0,084 ms por montagem.

    Levanta `ResumoAcimaDoLimite` quando nem sem imovel nenhum cabe -- a
    rede de seguranca de `geracao.gerar_resumo` conta com isso.
    """
    texto = _texto_com(dossie, 0)
    for quantos in range(1, len(dossie.imoveis) + 1):
        candidato = _texto_com(dossie, quantos)
        # `.strip()` porque e o que `validar` mede. Comparar outro
        # comprimento faria a busca aceitar um texto que `validar` recusa.
        if len(candidato.strip()) > LIMITE_DE_CARACTERES:
            break
        texto = candidato
    return validar(texto)
