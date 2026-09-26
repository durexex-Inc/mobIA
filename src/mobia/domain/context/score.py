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
from mobia.domain.configuracao.vigente import PESOS_DE_REFERENCIA, Pesos
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import campos_obrigatorios_preenchidos

PONTOS_POR_CAMPO_OBRIGATORIO = 5

# Os pontos de REFERENCIA, escritos contra os tetos de `PESOS_DE_REFERENCIA`.
# Ate a TEC-198 este comentario dizia "constantes de modulo, e nao
# configuracao", e que torna-las alteraveis era do epico de configuracao. A
# TEC-198 as tornou -- sem mexer nelas: o administrador configura o TETO de
# cada fator (`configuracao/vigente.py::Pesos`), e `_escalar` leva estes pontos
# para a escala dele. Com os pesos padrao, o score e o de antes.
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


def _escalar(pontos: int, peso: int, referencia: int) -> int:
    """Os pontos de referencia na escala do peso configurado. TEC-198, D3.

    Arredonda fator a fator, para o inteiro mais proximo: com urgencia 30,
    IMEDIATA 25 -> 30, ATE_3_MESES 15 -> 18, ATE_6_MESES 8 -> 9,6 -> 10. O
    `round` do Python arredonda metade para o par, e aqui isso nao importa --
    as metades exatas so aparecem em pesos impares, e o erro e de meio ponto
    num fator.

    **Com `peso == referencia` devolve `pontos` exato**, sem passar por
    divisao: e a garantia de que a configuracao padrao nao move score nenhum,
    nem por arredondamento.
    """
    if peso == referencia:
        return pontos
    return round(pontos * peso / referencia)


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
    # TEC-172, RN-12.4. O sexto fator, e o unico que SUBTRAI. Nao tem default,
    # de proposito: com um, `_score_do_registro` (`context/repositorio.py`)
    # reconstruiria da trilha um score sem penalidade e `causas_do_recalculo`
    # nunca veria a coluna se mover -- a linha que explica o desconto deixaria
    # de nascer, em silencio, e o defeito so apareceria na trilha de um lead
    # que faltou.
    penalidade: int

    @property
    def total(self) -> int:
        """Os cinco fatores menos a penalidade, com piso em zero.

        **O piso mora aqui, e nao em `penalidade`** (TEC-172): a coluna
        acumula de verdade, e cortar na acumulacao faria o segundo nao
        comparecimento de um lead ja zerado nao ser registrado. O piso nao
        esconde distincao nenhuma -- `temperatura_de` ja trata tudo abaixo de
        40 como FRIO --, e um total negativo nao significa nada na escala da
        RN-06.1.
        """
        bruto = self.completude + self.urgencia + self.catalogo + self.engajamento + self.capacidade
        return max(0, bruto - self.penalidade)


def calcular_score(
    estado: LeadQualification | None,
    *,
    mensagens_do_lead: int = 0,
    imoveis_compativeis: int = 0,
    recusados: frozenset[str] = frozenset(),
    pesos: Pesos = PESOS_DE_REFERENCIA,
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
    `IMEDIATA`, pagamento a vista e seis mensagens soma **70**, com
    `esta_qualificado` False; um lead qualificado que so nao disse como
    pagaria soma **66**.

    **A TEC-151 fechou a consequencia disso, e nao aqui.** Este score continua
    sem saber da qualificacao -- e deliberado, e nada nesta funcao mudou --,
    mas quem deriva a temperatura combina os dois: `temperatura_de`
    (`context/temperatura.py`) recebe `qualificado` e aplica teto `MORNO`, de
    forma que o primeiro exemplo acima NAO chega a QUENTE. E emenda E-01 a
    RN-06.2, e o motivo foi a RN-06.5: QUENTE faz o telefone do corretor
    tocar. **Quem for ordenar a fila continua tendo de combinar o total com
    `esta_qualificado`, e nunca usar o total sozinho** -- a temperatura ja o
    faz, o total cru nao.

    **O engajamento nao decai.** Nao ha janela de recencia: oito mensagens de
    quatro meses atras valem 15 para sempre, e duas de hoje valem 10 -- a
    contribuicao DESTE fator so sobe ao longo da vida da conversa. Onde o
    recalculo vive e decisao da TEC-151/TEC-152, mas a forma do fator e
    decidida aqui, e por isso a lacuna e desta card.

    **O total nunca foi monotono, e a TEC-148 abriu mais uma forma de ele
    cair.** `urgencia` e `capacidade` ja caiam antes desta branch, porque
    `campos_a_gravar` e "mais novo vence" -- a docstring dela diz isso --, e
    o lead que informa IMEDIATA e depois SEM_PRESSA perde os 25 pontos de
    urgencia; a docstring de `causas_do_recalculo` usa uma queda de urgencia
    como exemplo. O que so subia era a **completude**, porque valor gravado
    nunca e apagado -- e e ela que a recusa agora derruba em 5 pontos (ver
    `recusados` abaixo), com a trilha da TEC-152 registrando a queda sob
    `CAUSA_CAMPOS_OBRIGATORIOS`. Quem ordenar a fila nao pode supor que o
    numero de ontem e um piso.

    `imoveis_compativeis` tem default zero porque a busca de imoveis
    (TEC-158) nao existe, e a card prescreve que ate la o fator contribua
    zero. Quando ela existir, o chamador passa o numero real e nenhuma linha
    daqui muda.

    **`recusados` fecha a divergencia que esta card declarou.** Ate a
    TEC-148, campo recusado ainda pontuava a completude sobre um valor de um
    turno anterior, porque `calcular_score` nao recebia o conjunto. Recebe
    agora, e a regra e a mesma de `esta_qualificado`: recusado nao conta,
    mesmo com valor na coluna.

    **Apenas a completude consulta a recusa.** Nenhum outro dos cinco fatores
    o faz -- em particular, recusar `forma_pagamento` nao mexe na capacidade,
    que continua pontuando "a avaliar" pela coluna. Fica declarado.

    Keyword-only como os dois vizinhos, por consistencia da assinatura.
    """
    if estado is None:
        return Score(
            completude=0, urgencia=0, catalogo=0, engajamento=0, capacidade=0, penalidade=0
        )

    return Score(
        completude=_escalar(
            campos_obrigatorios_preenchidos(estado, recusados) * PONTOS_POR_CAMPO_OBRIGATORIO,
            pesos.completude,
            PESOS_DE_REFERENCIA.completude,
        ),
        urgencia=_escalar(
            _PONTOS_POR_URGENCIA.get(estado.urgencia or "", 0),
            pesos.urgencia,
            PESOS_DE_REFERENCIA.urgencia,
        ),
        catalogo=_escalar(
            _pontos_do_catalogo(imoveis_compativeis), pesos.catalogo, PESOS_DE_REFERENCIA.catalogo
        ),
        engajamento=_escalar(
            _pontos_do_engajamento(mensagens_do_lead),
            pesos.engajamento,
            PESOS_DE_REFERENCIA.engajamento,
        ),
        capacidade=_escalar(
            _PONTOS_POR_CAPACIDADE.get(
                estado.forma_pagamento or "", _PONTOS_SEM_FORMA_DE_PAGAMENTO
            ),
            pesos.capacidade,
            PESOS_DE_REFERENCIA.capacidade,
        ),
        # TEC-172. Sai da coluna e nao de parametro, ao contrario dos dois
        # fatores que dependem de dados de fora de `LeadQualification`: a
        # penalidade MORA nesta linha, entao le-la aqui nao acrescenta
        # consulta nenhuma nem torna a funcao menos testavel.
        #
        # **`or 0` porque a coluna e NOT NULL no banco e mesmo assim pode vir
        # `None` aqui.** O `server_default` so age no INSERT: um
        # `LeadQualification(...)` montado em memoria -- o que todo teste
        # unitario faz, e o que `gravar_estado` tem em maos antes do flush --
        # nao passou por ele e devolve `None`. Sem a normalizacao, a subtracao
        # abaixo levanta `TypeError` num caminho que o mypy nao ve, porque o
        # tipo declarado e `int`. Nenhuma linha VINDA do banco e nula.
        penalidade=estado.penalidade_pontos or 0,
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
