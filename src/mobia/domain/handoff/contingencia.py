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

# Teto da lista de "## Imoveis apresentados".
#
# Como se chegou a 7: montei o texto do pior caso do teste
# `test_um_dossie_grande_ainda_cabe_no_limite` -- 40 imoveis com todos os
# campos preenchidos (reacao "DESCARTOU" e motivo_descarte "PRECO" em todos,
# a linha mais longa que `imoveis()` escreve por item), mais regiao,
# campos_recusados, perguntados_sem_resposta e score_fatores no maior
# tamanho plausivel -- e medi `len(montar(...))` variando o teto:
#
#   teto  6 -> 1392   teto  7 -> 1448   teto  8 -> 1504   teto 10 -> 1617
#
# 8 ja estoura os 1.500 da RN-15.2 nesse cenario; 7 e o maior valor que ainda
# cabe, com 52 caracteres de folga. Nao e arredondado por estetica: e o maior
# testado que passa.
TETO_DE_IMOVEIS = 7


def montar(dossie: Dossie) -> str:
    """Os seis blocos da RN-15.1, montados so de fatos que ja vieram do banco.

    Sem chamada de modelo, sem redacao: quando o resumo redigido falha (D7),
    isto e o que sobra para o corretor, e por isso nao pode falhar por sua
    vez. `validar()` e o mesmo dos dois modos -- ver o cabecalho do modulo.
    """
    forcada = (
        f" (forcada por {', '.join(dossie.temperatura_forcada_motivos)})"
        if dossie.temperatura_forcada_motivos
        else ""
    )
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
            pontos_de_atencao(dossie),
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
