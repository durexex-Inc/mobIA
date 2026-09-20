import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from mobia.domain.agente.citacao import Divergencia, divergencias_de
from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import Extracao, Intencao, normalizar_regiao

# Alvo do card. Abaixo do piso o merge e barrado; entre os dois, avisa.
ALVO_PCT = 90
PISO_DE_BLOQUEIO_PCT = 84

# O piso da extracao vem do card (RF-05, secao 4.4 do SRS): 85%. Diferente do
# `PISO_DE_BLOQUEIO_PCT` de intencao, que e 84.
PISO_DE_PRECISAO_DA_EXTRACAO_PCT = 85

# Abaixo deste numero de turnos um unico turno vale mais de 0,8% e a faixa
# amarela deixa de absorver o ruido entre execucoes.
#
# Medido em 2026-08-29 (TEC-246): o corpus tem 146 turnos e o pior caso de
# abandono de `TETO_DE_CONVERSAS_ABANDONADAS` conversas entrega 129. O piso
# continua em 120 de proposito -- ele e estatistico, e nao de erosao de
# amostra, entao a conta do pior caso nao o governa.
PISO_DE_TURNOS = 120

# Piso de anotacao, irmao do PISO_DE_TURNOS. Sem ele, anotar tres turnos
# faceis daria precisao alta num corpus que nao mede nada -- o mesmo furo do
# corpus so-positivo, na outra direcao.
#
# Medido em 2026-08-29 (TEC-245): sao 55 positivos, e o pior caso de abandono
# de `TETO_DE_CONVERSAS_ABANDONADAS` conversas tira 15, entao a execucao mais
# azarada ainda entrega 40. O piso fica em 38, com folga de dois. A folga
# anterior era de UM, e nao de dois (31 contra 30): a margem mudou de
# tamanho aqui.
#
# Medido em 2026-08-29 (TEC-246): o corpus cresceu para 62 positivos, e o
# pior caso de abandono passou a 47. O piso sobe para 45, folga de dois (47
# contra 45) -- do mesmo tamanho da medicao anterior, mas por medicao e nao
# por convencao: esta constante nasceu na TEC-145 com folga de um e nao
# carrega margem fixa nenhuma. Quem tem folga de dois desde a origem e a
# irma `PISO_DE_TURNOS_NEGATIVOS`, criada pela TEC-238 -- que nunca mexeu
# nesta aqui.
PISO_DE_TURNOS_ANOTADOS = 45

# Piso dos turnos anotados como "o lead nao afirmou nada" (`campos: {}`).
# Irmao de `PISO_DE_TURNOS_ANOTADOS` na terceira direcao: aquele responde
# "sobrou amostra para medir acerto?", este responde "sobrou amostra para
# pegar invencao?".
#
# Os dois sao separados de proposito. Um piso unico sobre "todo turno
# anotado" se auto-satisfaria: 30 turnos negativos sem invencao nenhuma
# dariam denominador zero, e `faixa_de` levanta `ValueError` em vez de
# reportar -- o mesmo furo que o piso existe para fechar, entrando por outra
# porta.
#
# O numero vem do pior caso de abandono, como o de `TETO_DE_CONVERSAS_ABANDONADAS`:
# sao 37 negativos -- a TEC-238 anotou 39, e esta revisao tirou dois
# (`follow-up-03` indice 1 e `aluguel-09` indice 2) por serem pergunta de
# processo que pressupoe campo, e nao ausencia de afirmacao. As cinco
# conversas com mais negativos somam 12, entao a execucao mais azarada ainda
# entrega 37 - 12 = 25. O piso fica em 23, com folga de dois.
#
# Medido em 2026-08-29 (TEC-245): a TEC-242 e a triagem desta card levaram o
# corpus a 66 negativos, e o pior caso de abandono passou a 51. O piso sobe
# para 49, com a mesma folga de dois que tinha antes desta card (25 contra
# 23).
#
# Medido em 2026-08-29 (TEC-246): o corpus cresceu para 70 negativos, e o
# pior caso de abandono passou a 55. O piso sobe para 53, com a mesma folga
# de dois que carrega desde a TEC-238 (55 contra 53).
PISO_DE_TURNOS_NEGATIVOS = 53

# Quantas conversas a execucao pode perder para falha de infraestrutura antes
# de deixar de valer como medida.
#
# O numero vem do corpus e do piso, nao do gosto. Medido em 2026-08-29
# (TEC-246): hoje sao 53 conversas e 146 turnos (eram 50 e 138 antes desta
# card), e a folga do piso e 146 - 120 = 26 turnos, contra 138 - 120 = 18
# antes desta card. O pior caso de cinco abandonos nao e 5 x 3: a TEC-239 deu
# um quarto turno a `compra-02` e a `compra-08`, entao as cinco conversas
# mais longas somam 4 + 4 + 3 + 3 + 3 = 17 turnos (o mesmo pior caso de
# sempre -- o corpus cresceu em conversas menores), e sobra folga de nove
# (129 - 120), contra a folga de um que a conta tinha antes desta card (121 -
# 120 com os 138 turnos de entao). O teto de 5 continua valido -- abandono
# nenhum consegue furar o piso --, e a folga so cresceu com o corpus: com
# seis o pior caso passa a 146 - 20 = 126 turnos, ainda acima do piso; e so a
# partir de nove abandonos o pior caso cai a 146 - 29 = 117, abaixo de 120,
# ponto em que os dois limites passariam a reprovar a mesma execucao por
# motivos diferentes, com a mensagem decidida por quem for verificado
# primeiro. Antes desta card, esse ponto de virada era em seis (138 - 20 =
# 118): o corpus cresceu mais rapido no total de turnos do que nas cinco
# conversas mais longas, e a margem entre o teto de 5 e a reprovacao dupla
# alargou de um abandono extra para quatro.
#
# A conta e sobre as conversas mais **longas**, e nao sobre as mais anotadas.
# Essa propriedade -- abandonar as cinco com mais anotacao ainda deixava a
# amostra abaixo de `PISO_DE_TURNOS_ANOTADOS` -- valia em 57aee2d (38 - 13 =
# 25, abaixo do piso de 30), mas a TEC-242 deu tres anotacoes a `compra-06` e
# a colocou entre as cinco conversas com mais anotacao. Medido em 2026-08-29
# (TEC-246), a mesma conta da 62 - 15 = 47, ACIMA do piso -- que hoje e 45,
# e nao os 38 da TEC-245 nem os 30 da linha acima: a propriedade deixou de
# valer.
#
# Isso nao muda a escolha de contar conversas **longas** neste teto, que
# continua de pe pelo outro motivo ja escrito abaixo -- o teto mede
# confiabilidade de rede, o piso mede amostra --, so tira o apoio extra que
# esta linha dava a ela.
#
# Com os dois assim, cada um mede uma coisa. O piso conta turnos e responde
# "sobrou amostra suficiente?". Este teto conta conversas e responde "a rede
# estava confiavel?": cinco conversas perdidas nao e azar de requisicao --
# `MAX_TENTATIVAS = 1` foi gasto em cada uma delas, em cinco momentos
# distintos da execucao --, e sim uma execucao que atravessou um incidente, e
# ai nem os turnos que passaram merecem ser lidos como medida do prompt.
TETO_DE_CONVERSAS_ABANDONADAS = 5

# A `acuracia_efetiva` usa as MESMAS faixas da crua -- `ALVO_PCT` e
# `PISO_DE_BLOQUEIO_PCT` -- e nao um piso proprio.
#
# Ela teve um piso proprio de 50% enquanto a baseline nao existia. Aquilo era
# andaime: ninguem sabia qual acuracia efetiva era saudavel, cravar 90/84 seria
# piso nao medido, e um piso nao medido podia abrir VERMELHO na primeira
# execucao sem regressao nenhuma. O piso de 50% respondia so "a calibragem
# desabou por completo?", porque com todo turno rebaixado sobram como acerto
# apenas os rotulos que ja eram INDEFINIDA -- 9 de 136, ou 6,6%.
#
# A primeira execucao paga rodou em 2026-08-27 e mediu 126/136, ou 92,6%. Com
# isso o andaime sai, por um motivo que a medicao tornou obvio: os 90% do
# criterio de aceite sao sobre o que o lead experimenta, e o lead experimenta a
# intencao **efetiva**, nao o palpite cru. O alvo pertence a esta metrica ao
# menos tanto quanto a outra.
#
# Consequencia boa: degradacao **parcial** de calibragem passa a bloquear. Com
# o piso de 50% ela nao bloqueava -- metade do corpus rebaixado ainda dava 50%
# e passava --, e essa limitacao estava declarada. Deixou de existir.
#
# Consequencia a aceitar: 92,6% deixa 2,6 pontos entre a medida e o alvo, e o
# ruido esperado entre execucoes e da ordem de +/-1,5%. A efetiva vai oscilar
# entre VERDE e AMARELO perto da borda. AMARELO nao bloqueia; sao 8,6 pontos
# ate o piso de 84%. E a TEC-235 deve subir a efetiva, nao baixa-la: a medicao
# mostrou que o rebaixamento perdeu 4 acertos e recuperou zero.


class Faixa(StrEnum):
    VERDE = "VERDE"
    AMARELO = "AMARELO"
    VERMELHO = "VERMELHO"
    SEM_MECANISMO = "SEM_MECANISMO"


@dataclass(frozen=True)
class Classificacao:
    """Um turno medido: o que o corpus anotou, e o que o modelo devolveu.

    `confianca` esta aqui e nao e opcional. Sem ela nao ha como recalibrar
    `LIMIAR_DE_DESAMBIGUACAO` -- a calibragem precisa da tripla (esperada,
    obtida, confianca), e nenhuma outra execucao produz essas triplas. E,
    principalmente, sem ela nao ha como medir o que producao de fato roteia:
    `executar_turno` nao roteia por `obtida`, roteia pela efetiva. Um ajuste
    de prompt que mantenha a acuracia crua e arruine a calibragem da confianca
    passaria verde num gate que so olhasse `obtida`, enquanto producao
    desambiguaria em todo turno.
    """

    conversa_id: str
    indice: int
    esperada: Intencao
    obtida: Intencao
    confianca: Decimal

    @property
    def certa(self) -> bool:
        return self.esperada is self.obtida

    @property
    def efetiva(self) -> Intencao:
        """A intencao que producao rotearia neste turno.

        Delega a `intencao_efetiva`, a mesma funcao que o TEC-136 e o TEC-137
        leem. Reimplementar `confianca < LIMIAR_DE_DESAMBIGUACAO` aqui criaria
        um segundo limiar, e o gate mediria a copia em vez do original.
        """
        return intencao_efetiva(self.obtida, self.confianca)

    @property
    def certa_na_efetiva(self) -> bool:
        return self.esperada is self.efetiva

    @property
    def desambiguaria(self) -> bool:
        """Se a confianca deste turno nao sustenta a classificacao.

        `desambiguado_em=None` de proposito: o eval nao tem banco nem episodio
        em aberto, e a pergunta aqui e "a confianca sozinha bastaria para
        perguntar em vez de responder?". Com o marcador vazio,
        `deve_desambiguar` reduz exatamente a
        `confianca < LIMIAR_DE_DESAMBIGUACAO` -- que e o que se quer contar,
        obtido da funcao de producao em vez de uma segunda copia do limiar.
        """
        return deve_desambiguar(self.confianca, None)


@dataclass(frozen=True)
class FalhaDeInfraestrutura:
    """Uma conversa que a execucao perdeu para a rede, nao para o prompt.

    Fica separada das `Classificacao` porque tem de aparecer no relatorio sem
    virar turno errado: vermelho por 429 e vermelho por regressao pedem acoes
    opostas (re-rodar contra investigar), e um relatorio que funde os dois faz
    o leitor escolher errado.
    """

    conversa_id: str
    indice: int
    erro: str
    # O porque, quando o provedor o manda (TEC-237). `erro` continua sendo so o
    # nome da classe; `motivo` carrega status, tipo e mensagem do corpo de erro
    # da API -- que e gerado pelo servidor, ao contrario de `str(exc)`. `None`
    # para tudo que nao for erro de protocolo do provedor, que e a garantia:
    # ver `motivo_do_provedor` em `mobia.infra.anthropic`.
    motivo: str | None = None


@dataclass(frozen=True)
class ResumoDeConfianca:
    """O que o limiar faz com as classificacoes, em numeros.

    Nao carrega faixa: e diagnostico, nao gate. Quem bloqueia por calibragem
    de confianca e a acuracia efetiva.
    """

    turnos: int
    abaixo_do_limiar: int
    acertos_rebaixados: int
    acertos_recuperados: int


@dataclass(frozen=True)
class ResultadoDaMetrica:
    nome: str
    faixa: Faixa
    acertos: int | None
    total: int | None
    detalhe: str


def faixa_de(
    acertos: int,
    total: int,
    *,
    alvo: int = ALVO_PCT,
    piso: int = PISO_DE_BLOQUEIO_PCT,
) -> Faixa:
    """Compara em aritmetica inteira, nunca em float.

    `acertos * 100 >= total * ALVO_PCT` e exato por construcao: os dois lados
    sao inteiros e nenhuma divisao acontece. Nao e que float erraria a borda
    -- `126/150 >= 0.84` e `135/150 >= 0.9` dao True, os dois. E que com
    inteiros ninguem precisa verificar isso: nao ha representacao decimal no
    caminho sobre a qual raciocinar, entao a borda nao e um caso a analisar.

    `alvo` e `piso` sao parametros com default porque a extracao (TEC-145) tem
    piso proprio de 85. Uma segunda funcao de faixa foi tentada na TEC-210
    (`faixa_de_catastrofe`) e deletada no PR #10: duas funcoes de faixa
    divergem, e a divergencia so aparece na borda.
    """
    if total <= 0:
        raise ValueError("nada medido nao e sucesso: total de turnos e zero")
    if acertos * 100 >= total * alvo:
        return Faixa.VERDE
    if acertos * 100 >= total * piso:
        return Faixa.AMARELO
    return Faixa.VERMELHO


def _detalhe(acertos: int, total: int, referencia: str) -> str:
    pct = acertos * 100 / total
    return f"{acertos}/{total} ({pct:.1f}%), {referencia}"


def acuracia_de_intencao(classificacoes: Sequence[Classificacao]) -> ResultadoDaMetrica:
    """Acuracia do palpite cru, contra o rotulo do corpus.

    Mede o classificador: quanto ele acerta quando se ignora o quanto ele diz
    estar seguro. Sozinha, e cega para calibragem -- ver `acuracia_efetiva`.
    """
    total = len(classificacoes)
    acertos = sum(1 for c in classificacoes if c.certa)
    # Antes de `_detalhe`, que divide: e `faixa_de` que recusa total zero.
    faixa = faixa_de(acertos, total)
    return ResultadoDaMetrica(
        nome="acuracia de intencao",
        faixa=faixa,
        acertos=acertos,
        total=total,
        detalhe=_detalhe(acertos, total, f"alvo {ALVO_PCT}%, piso {PISO_DE_BLOQUEIO_PCT}%"),
    )


def acuracia_efetiva(classificacoes: Sequence[Classificacao]) -> ResultadoDaMetrica:
    """Acuracia do que producao roteia, e nao do que o modelo palpitou.

    Metrica propria, e bloqueia pelas mesmas faixas da crua. Ela nao pode ser
    detalhe da outra: uma linha informativa dentro de `acuracia de intencao`
    nunca ficaria VERMELHA, e e justamente a regressao invisivel na acuracia
    crua que o gate precisa barrar.

    Herdar 90/84 seria piso nao medido enquanto a baseline nao existia -- por
    isso ela nasceu com piso proprio. A baseline existe desde 2026-08-27
    (92,6%), e o andaime saiu: ver o comentario de `ALVO_PCT`.

    Separadas, as duas ainda diferenciam o diagnostico -- as duas vermelhas e
    o classificador degradando; a crua verde e esta vermelha e a calibragem da
    confianca desabando com o palpite intacto.

    Ela pode ficar acima da crua, e nao e bug: num turno cujo rotulo e
    INDEFINIDA, rebaixar um palpite mal-confiante acerta o rotulo. Ver
    `ResumoDeConfianca.acertos_recuperados`.
    """
    total = len(classificacoes)
    acertos = sum(1 for c in classificacoes if c.certa_na_efetiva)
    # Antes de `_detalhe`, que divide: e a faixa que recusa total zero.
    faixa = faixa_de(acertos, total)
    return ResultadoDaMetrica(
        nome="acuracia efetiva (o que producao roteia)",
        faixa=faixa,
        acertos=acertos,
        total=total,
        detalhe=_detalhe(
            acertos,
            total,
            f"alvo {ALVO_PCT}%, piso {PISO_DE_BLOQUEIO_PCT}%",
        ),
    )


def resumo_de_confianca(classificacoes: Sequence[Classificacao]) -> ResumoDeConfianca:
    return ResumoDeConfianca(
        turnos=len(classificacoes),
        abaixo_do_limiar=sum(1 for c in classificacoes if c.desambiguaria),
        acertos_rebaixados=sum(1 for c in classificacoes if c.certa and not c.certa_na_efetiva),
        acertos_recuperados=sum(1 for c in classificacoes if not c.certa and c.certa_na_efetiva),
    )


def erros(classificacoes: Sequence[Classificacao]) -> list[Classificacao]:
    """Os turnos que o relatorio precisa nomear, na ordem em que rodaram.

    Inclui o turno cujo palpite estava certo e foi rebaixado pela confianca:
    ele nao aparece na acuracia crua nem na matriz de confusao, e e o caso que
    mais precisa de nome, porque e o unico que so a calibragem explica.
    """
    return [c for c in classificacoes if not c.certa or not c.certa_na_efetiva]


def matriz_de_confusao(
    classificacoes: Sequence[Classificacao],
) -> dict[Intencao, dict[Intencao, int]]:
    """Agrupa por `obtida`, o palpite cru, e nao pela efetiva.

    De proposito: a matriz existe para dizer qual intencao escorre para qual, e
    isso e sobre o classificador. Agrupada pela efetiva, todo erro de
    calibragem viraria uma coluna INDEFINIDA que esconde para onde o palpite
    de fato foi.
    """
    matriz: dict[Intencao, dict[Intencao, int]] = defaultdict(lambda: defaultdict(int))
    for c in classificacoes:
        matriz[c.esperada][c.obtida] += 1
    return {esperada: dict(obtidas) for esperada, obtidas in matriz.items()}


# RN-04.2: teto de caracteres por mensagem do agente. Vem do SRS, e nao de
# medicao -- e regra de produto sobre o que o lead recebe, nao um limite
# tecnico.
MAX_CARACTERES_DA_RESPOSTA = 600

# RN-04.2 diz "uma pergunta por vez", e o teto de 1 era a leitura literal disso.
# A TEC-255 subiu para 2, contra a letra da regra e a favor do que ela protege:
# "nunca um questionario de cinco itens".
#
# A regra e a MESMA sentenca do teto de 600 caracteres acima -- RN-04.2 carrega
# tres clausulas: 600 caracteres, no maximo 2 mensagens consecutivas, e uma
# pergunta por vez. "Uma pergunta por turno" reaparece em RN-05.4. Ate 01/09/2026
# este comentario citava RN-04.7, que e outra regra (indicador de digitacao
# acima de 4s) e nao tem relacao com perguntas; a emenda E-01 do SRS versionado
# em `docs/srs/` corrige RN-04.2 e RN-05.4, e nao RN-04.7.
#
# O que as duas execucoes de 31/08 mostraram, sobre 294 turnos medidos: as
# violacoes sao quase todas de exatamente duas perguntas de qualificacao
# genuinas ("qual regiao? E precisa de vaga?"), e o bloco que a regra teme nao
# aparece -- o maior turno observado tem TRES perguntas, uma vez
# (`follow-up-07[0]`, execucao das 13:19). O teto de 1 marcava 19% dos turnos
# como violacao de um comportamento que ninguem pretendia consertar, e regua
# que ninguem pretende obedecer vira regua ignorada.
#
# A regua NAO fica cega ao subir: recalculadas sob o teto de 2, as duas
# execucoes dao 144/147 e 146/147, e o que sobra violando e justamente o turno
# de tres perguntas e as violacoes de comprimento.
MAX_PERGUNTAS_POR_TURNO = 2

# Piso medido, e nao mais o andaime de 50% que viveu aqui ate a TEC-255. O
# andaime existia porque o texto que o modelo devolve nunca tinha sido medido;
# a TEC-255 mediu, recalculando os dois relatorios de 31/08 sob o teto novo:
# 98,0% e 99,3%.
#
# 90 fica oito pontos abaixo do pior ponto observado. E a escolha conservadora
# entre as que estavam na mesa (a outra era 95): dois pontos de medicao sao
# pouco para um piso apertado, e um piso que abre VERMELHO sem regressao real e
# exatamente o erro que o andaime avisava -- o que a `acuracia_efetiva` viveu
# ate a TEC-210 medir.
#
# Este piso fica ACIMA de `PISO_DE_BLOQUEIO_PCT`, ao contrario do andaime, e e
# deliberado: 84 e o piso da acuracia de intencao, medido sobre outra coisa, e
# nao um teto para os pisos das metricas irmas.
PISO_DE_ADERENCIA_AO_TOM_PCT = 90

# Alvo proprio, e nao o `ALVO_PCT` global de 90. `faixa_de` devolve VERDE em
# `>= alvo` e AMARELO em `>= piso`: com os dois em 90 o segundo teste nunca
# seria alcancado, a metrica viraria binaria e passaria a bloquear o gate
# abaixo de 90 -- mais duro que o andaime que ela substitui, e o oposto de ter
# escolhido o piso conservador.
ALVO_DE_ADERENCIA_AO_TOM_PCT = 98

# Blocos Unicode de emoji, na pratica e nao na norma: pictogramas, emoticons,
# transporte, simbolos diversos e dingbats, mais o seletor de variacao que faz
# um caractere comum renderizar como emoji.
#
# **Deliberadamente aproximado.** Nao existe propriedade Unicode "e emoji" que
# o `re` da stdlib exponha, e trazer dependencia para contar figurinha num
# diagnostico seria caro demais. O que esta faixa erra: bandeiras compostas
# contam como dois, e alguns simbolos matematicos antigos entram sem ser
# emoji. Para o uso aqui -- dizer se a resposta tem figurinha e quantas --
# isso basta, e a imprecisao esta escrita.
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u2190-\u21ff]")


@dataclass(frozen=True)
class RespostaObservada:
    """O texto que o agente devolveu num turno, com o endereco.

    Existe porque o texto era gerado em toda execucao paga e **descartado**:
    `resposta.resposta` alimentava o proxy de reperguntas e o historico, e
    mais nada. Medir o formato nao custa chamada nenhuma -- o texto ja esta
    ali.
    """

    conversa_id: str
    indice: int
    texto: str


@dataclass(frozen=True)
class ViolacaoDeFormato:
    """Uma regra de formato que a resposta de um turno nao cumpriu.

    `medido` carrega o valor que estourou -- 812 caracteres, 3 perguntas --
    porque saber que violou sem saber por quanto nao diz se e ajuste de prompt
    ou desvio grosseiro.

    `texto` carrega a resposta inteira, e a primeira execucao provou por que.
    Em 31/08 sairam 26 violacoes de "uma pergunta", 24 delas com exatamente
    duas -- e **nao havia como saber** se eram duas perguntas de verdade ou
    erro do proxy de `?`, porque so o endereco e a contagem viajavam. Descobrir
    exigiria outra execucao paga. E a mesma licao que `Discrepancia` ja
    encodava ao carregar `esperado` e `obtido` crus: endereco sozinho nao
    diagnostica.

    Nao ha dado de lead real aqui. O corpus e ficticio e o texto e a resposta
    do **agente** a ele -- por isso pode ir para um relatorio commitado, ao
    contrario de tudo que a regra de PII cobre em producao.
    """

    conversa_id: str
    indice: int
    regra: Literal["comprimento", "perguntas"]
    medido: int
    texto: str


def violacoes_de_formato(respostas: Sequence[RespostaObservada]) -> list[ViolacaoDeFormato]:
    """As duas regras do RF-04 que sao decidiveis sobre o texto.

    **A terceira regra do card nao esta aqui, e nao por esquecimento.** "A
    informacao essencial nunca depende de emoji" exige entender o que a frase
    afirma -- se a figurinha substitui uma palavra ou so decora. Nenhuma
    contagem responde isso, entao ela nao vira criterio: `resumo_do_formato`
    reporta presenca e quantidade de emoji como diagnostico, e a parte de
    "essencial" fica declarada como nao mecanizada. Reportar um numero que nao
    mede a regra seria pior que reportar nenhum -- e o mesmo raciocinio de
    `sem_mecanismo`.

    Contar `?` e proxy, da mesma classe que `_reperguntou` no runner do eval, e
    erra nas duas direcoes: "cabe em R$ 500?" conta pergunta que nao pergunta
    nada ao lead, e "me diz qual regiao voce prefere" escapa por nao ter `?`.
    Pista, nao prova.
    """
    violacoes: list[ViolacaoDeFormato] = []
    for resposta in respostas:
        caracteres = len(resposta.texto)
        if caracteres > MAX_CARACTERES_DA_RESPOSTA:
            violacoes.append(
                ViolacaoDeFormato(
                    conversa_id=resposta.conversa_id,
                    indice=resposta.indice,
                    regra="comprimento",
                    medido=caracteres,
                    texto=resposta.texto,
                )
            )
        perguntas = resposta.texto.count("?")
        if perguntas > MAX_PERGUNTAS_POR_TURNO:
            violacoes.append(
                ViolacaoDeFormato(
                    conversa_id=resposta.conversa_id,
                    indice=resposta.indice,
                    regra="perguntas",
                    medido=perguntas,
                    texto=resposta.texto,
                )
            )
    return violacoes


def aderencia_ao_tom(respostas: Sequence[RespostaObservada]) -> ResultadoDaMetrica:
    """Fracao das respostas que cumprem as duas regras decidiveis.

    Por resposta e nao por violacao: o lead vive o turno, e um turno que
    estoura o tamanho **e** faz tres perguntas e um turno ruim, nao dois.

    Deriva de `violacoes_de_formato` em vez de refazer as comparacoes, para as
    duas contas nao divergirem em silencio -- a licao que `campos_a_gravar` e
    `_subcontagem` ja tinham deixado neste projeto.
    """
    violadas = {(v.conversa_id, v.indice) for v in violacoes_de_formato(respostas)}
    total = len(respostas)
    acertos = total - len(violadas)
    return ResultadoDaMetrica(
        nome="aderencia ao tom",
        faixa=faixa_de(
            acertos,
            total,
            alvo=ALVO_DE_ADERENCIA_AO_TOM_PCT,
            piso=PISO_DE_ADERENCIA_AO_TOM_PCT,
        ),
        acertos=acertos,
        total=total,
        detalhe=_detalhe(
            acertos,
            total,
            f"alvo {ALVO_DE_ADERENCIA_AO_TOM_PCT}%, piso {PISO_DE_ADERENCIA_AO_TOM_PCT}%",
        ),
    )


# O nome carrega o escopo de proposito (D4 do desenho). A guarda da TEC-161
# cobre cifra e codigo; NAO cobre parafrase -- "tenho um bem espacoso na
# praia" sobre imovel inexistente passa, e a lacuna 1 daquela card declara
# isso. Sem o parenteses, um VERDE nesta linha diria a quem audita o RT-01
# que toda alucinacao esta coberta.
#
# `turnos sem invencao` foi recusado: colide com `com_invencao` neste mesmo
# modulo, que conta campo de extracao inventado em turno negativo.
NOME_DA_TAXA_DE_ALUCINACAO = "taxa de alucinacao (cifra e codigo)"

# A RNF-26 pede taxa abaixo de 2%, logo 98% de turnos ancorados. A metrica
# conta o complemento por dentro porque `faixa_de` e quanto-maior-melhor.
ALVO_DE_ANCORAGEM_PCT = 98

# ANDAIME, nao medida -- D6 do desenho. Substituir por piso medido quando
# houver execucoes, que foi o que a TEC-255 fez com a aderencia ao tom
# (trocou o andaime de 50 por 90 depois de medir). Gatear em 2% na primeira
# execucao seria gatear em ruido: esta metrica tem denominador FIXO (todos os
# turnos), entao o analogo honesto e `DISPERSAO_MEDIDA.base_fixa_pp`, e nao
# `uniao_pp` -- duas execucoes do MESMO codigo ja diferiram 2,1 pontos por
# essa conta (o `uniao_pp` de 5,7 e de uma metrica com denominador de uniao, e
# nao se aplica aqui). 2,1 pontos ja bastam para proibir gatear em 2%.
#
# **Este numero e propriedade do par modelo-detector, nao do modelo** (D2).
# Alargar a gramatica de `divergencias_de` faz a taxa subir sem o modelo ter
# piorado. Quem alargar re-mede o piso na mesma card, e a pergunta e "subiu
# porque o modelo piorou ou porque o detector melhorou?" antes de "quanto
# subo o piso?".
#
# Primeira medicao paga (2026-09-10): CI run 34471488445, workflow_dispatch
# no branch feat/tec-269-taxa-de-alucinacao, conclusao success, commit b059585.
# Corpus: 53 conversas, 147 turnos; 0 abandonadas. Resultado: 1/147 turnos com
# cifra sem base (0,7%), VERDE contra alvo <2%. Colaterais: intencao 98,0%
# VERDE, efetiva 95,9% VERDE, extracao 91,9% VERDE, tom 98,0% AMARELO.
#
# O piso fica em 50 de proposito -- registrar a medida agora, atuar depois
# quando houver historia.
PISO_ANDAIME_DE_ANCORAGEM_PCT = 50


@dataclass(frozen=True)
class InvencaoObservada:
    """Um turno cuja prosa citou cifra ou codigo sem base, com o endereco.

    Carrega as divergencias e nao so a contagem para uma secao de
    diagnostico FUTURA poder renderiza-las -- **essa secao nao existe
    ainda**. Hoje `divergencias` so e lido por dois testes unitarios:
    `taxa_de_alucinacao` conta so por `conversa_id`/`indice` e nunca passa
    este campo para `render`. E diferente de `ViolacaoDeFormato`, que carrega
    o mesmo tipo de detalhe e ELE chega ao relatorio -- aqui, descobrir qual
    foi a divergencia de um turno especifico ainda exige outra execucao paga.
    """

    conversa_id: str
    indice: int
    divergencias: tuple[Divergencia, ...]


def invencao_do_turno(
    texto: str,
    *,
    conversa_id: str,
    indice: int,
    candidatos: Sequence[Mapping[str, Any]],
    faixa: tuple[int | None, int | None],
) -> InvencaoObservada | None:
    """A invencao deste turno, ou `None` quando a prosa esta ancorada.

    Chama `divergencias_de` -- a MESMA funcao que `executar_turno` roda em
    producao -- e nao uma copia. Uma segunda definicao de "alucinacao" neste
    repo seriam duas medindo coisas diferentes com o mesmo nome, e a TEC-161
    recusou a gramatica gemea tres vezes dentro da propria branch.

    `candidatos` chega vazio em todo turno do corpus, porque o eval nao passa
    `porta` e portanto nao ha tool use (D1). Com lista vazia so a faixa que o
    MODELO EXTRAIU absolve -- e nao a que o lead declarou: `faixa` chega aqui
    a partir de `estado_acumulado`, que e alimentado por `campos_a_gravar`
    sobre a extracao do modelo, nunca pela anotacao do corpus. As duas
    coincidem quando a extracao acerta e divergem quando ela erra -- ver a
    lacuna 5 do desenho.
    """
    divergencias = divergencias_de(texto, candidatos=candidatos, faixa=faixa)
    if not divergencias:
        return None
    return InvencaoObservada(conversa_id=conversa_id, indice=indice, divergencias=divergencias)


def taxa_de_alucinacao(
    invencoes: Sequence[InvencaoObservada],
    respostas: Sequence[RespostaObservada],
) -> ResultadoDaMetrica:
    """Fracao dos turnos cuja prosa nao inventou cifra nem codigo.

    Por turno e nao por divergencia, pela mesma razao de `aderencia_ao_tom`:
    o lead vive o turno, e um turno que inventa dois precos e um turno ruim,
    nao dois.

    `acertos` conta turnos LIMPOS porque `faixa_de` e quanto-maior-melhor; o
    `detalhe` -- a unica coisa que o relatorio renderiza -- reporta a taxa na
    direcao que a RNF-26 pede. A inversao e deliberada (D5).
    """
    total = len(respostas)
    if total == 0:
        return sem_mecanismo(
            NOME_DA_TAXA_DE_ALUCINACAO,
            "nenhuma resposta sobreviveu a execucao",
        )
    sujos = len({(i.conversa_id, i.indice) for i in invencoes})
    acertos = total - sujos
    pct = sujos * 100 / total
    return ResultadoDaMetrica(
        nome=NOME_DA_TAXA_DE_ALUCINACAO,
        faixa=faixa_de(
            acertos,
            total,
            alvo=ALVO_DE_ANCORAGEM_PCT,
            piso=PISO_ANDAIME_DE_ANCORAGEM_PCT,
        ),
        acertos=acertos,
        total=total,
        detalhe=(
            f"{sujos}/{total} turnos com cifra sem base ({pct:.1f}%), "
            f"alvo <{100 - ALVO_DE_ANCORAGEM_PCT}%, "
            f"piso <{100 - PISO_ANDAIME_DE_ANCORAGEM_PCT}% (andaime), "
            f"sem busca no corpus"
        ),
    )


@dataclass(frozen=True)
class ResumoDoFormato:
    """Diagnostico do formato, aberto por regra. Nao carrega faixa.

    Quem bloqueia e `aderencia_ao_tom`; esta secao existe para dizer **o que
    fazer** com aquele numero -- se a violacao e de tamanho ou de perguntas
    decide entre encurtar o texto e mudar a instrucao, e sao consertos
    diferentes.
    """

    respostas: int
    violacoes: list[ViolacaoDeFormato]
    com_emoji: int
    emojis: int


def resumo_do_formato(respostas: Sequence[RespostaObservada]) -> ResumoDoFormato:
    com_emoji = sum(1 for r in respostas if _EMOJI.search(r.texto))
    return ResumoDoFormato(
        respostas=len(respostas),
        violacoes=violacoes_de_formato(respostas),
        com_emoji=com_emoji,
        emojis=sum(len(_EMOJI.findall(r.texto)) for r in respostas),
    )


@dataclass(frozen=True)
class ResumoDaInvencao:
    """Diagnostico da ancoragem: quais turnos citaram sem base. TEC-270.

    Nao carrega faixa nem bloqueia -- quem bloqueia e `taxa_de_alucinacao`,
    com os MESMOS turnos. Esta existe para dizer **quais**, que era a
    pergunta que ate a TEC-270 custava outra execucao paga: a TEC-269 ja
    coletava as divergencias em `InvencaoObservada`, e elas paravam em
    `_metricas_de` sem nunca chegar ao `render`.

    **`respostas` esta aqui para a secao poder dizer "0 de 147".** Um resumo
    montado so a partir da lista nao distingue "a execucao foi limpa" de "nao
    houve medicao", e a secao sumiria no primeiro caso -- que e justamente
    quando o leitor precisa saber que a medicao rodou. Secao que so aparece
    quando ha problema treina quem le a nao procura-la.
    """

    respostas: int
    turnos: list[InvencaoObservada]


def resumo_da_invencao(
    invencoes: Sequence[InvencaoObservada],
    respostas: Sequence[RespostaObservada],
) -> ResumoDaInvencao:
    """Espelha `resumo_do_formato`: a mesma forma para a mesma familia de secao.

    Nao recalcula nada -- `invencao_do_turno` ja decidiu o que e invencao, com
    a mesma `divergencias_de` que `executar_turno` roda em producao. Aqui so
    se agrupa para render.
    """
    return ResumoDaInvencao(respostas=len(respostas), turnos=list(invencoes))


# Marcadores de pergunta por campo. Moram aqui, e nao no runner do eval, porque
# dois proxies dependem deles e uma segunda copia divergiria: `_reperguntou`
# (perguntar o que o estado JA SABE) e `insistencias` (perguntar de novo o que
# o lead NAO respondeu). Sao perguntas opostas sobre a mesma deteccao.
#
# A lista veio de `evals/test_acuracia_de_intencao.py` sem uma virgula de
# mudanca, e os seis casos que a apertaram continuam travados em
# `tests/unit/test_evals_reperguntas.py`.
MARCADORES_DE_REPERGUNTA: dict[str, tuple[str, ...]] = {
    "regiao": (r"regiao", r"bairro", r"onde", r"localiza"),
    "quartos": (r"quartos?", r"dormitorios?"),
    "vagas": (r"vagas?", r"garagem"),
    "tipo_imovel": (r"apartamentos?", r"tipo de imovel"),
    "faixa_preco_max_centavos": (r"orcamento", r"faixa de preco", r"quanto pretende"),
    "urgencia": (r"prazo", r"quando pretende", r"pressa"),
    "forma_pagamento": (r"pagamento", r"financiamento", r"a vista"),
    "tem_imovel_para_vender": (r"imovel para vender", r"tem imovel"),
}


def campos_perguntados(texto: str) -> set[str]:
    """Sobre quais campos esta resposta parece perguntar.

    Proxy de palavra-chave, com as duas guardas que a TEC-210 apertou: exige
    `?` no texto -- sem isso "esse apartamento tem 2 quartos e 1 vaga" (o
    agente descrevendo um imovel) contaria tres perguntas -- e casa
    `\bmarcador\b` e nao substring crua, porque "onde" e substring de
    "responder".

    Erra nas duas direcoes mesmo assim, e isso esta declarado: uma pergunta com
    outra palavra escapa, e uma frase descritiva que termina perguntando outra
    coisa entra. Pista, nao prova.
    """
    if "?" not in texto:
        return set()
    baixo = texto.casefold()
    return {
        campo
        for campo, marcadores in MARCADORES_DE_REPERGUNTA.items()
        if any(re.search(rf"\b{marcador}\b", baixo) for marcador in marcadores)
    }


@dataclass(frozen=True)
class PerguntaObservada:
    """Os campos ainda **desconhecidos** sobre os quais o agente perguntou num
    turno.

    "Desconhecidos" e o filtro que separa esta medicao do proxy irmao: campo
    que ja esta no estado e reperguntado, e `_reperguntou` cuida disso. Aqui
    interessa o que o lead nao respondeu -- e que o agente pode estar
    reinsistindo.
    """

    conversa_id: str
    indice: int
    campos: frozenset[str]


@dataclass(frozen=True)
class Insistencia:
    """Um campo perguntado em mais de um turno da mesma conversa, sem resposta.

    `turnos` carrega todos os indices, e nao so a contagem: tres turnos
    seguidos e um caso pior que dois turnos separados por dez, e o endereco e
    o que permite ler as respostas sem pagar outra execucao.
    """

    conversa_id: str
    campo: str
    turnos: tuple[int, ...]


@dataclass(frozen=True)
class ResumoDeInsistencia:
    """Diagnostico. Nao carrega faixa e nao entra em `bloqueia`.

    Nao vira metrica porque ninguem decidiu ainda se reinsistir e defeito.
    Reinsistir **nao e errado em si**: se o lead ignorou, perguntar de novo e
    razoavel. O que a execucao de 31/08/2026 mostrou -- `compra-14` pedindo
    "regiao? E vaga?" nos turnos 0, 1 e 2, com a mesma formulacao -- e
    cadencia, nao a pergunta. Medir primeiro, decidir depois (TEC-256).
    """

    conversas: int
    insistencias: list[Insistencia]

    @property
    def conversas_afetadas(self) -> int:
        return len({i.conversa_id for i in self.insistencias})


def insistencias(perguntas: Sequence[PerguntaObservada]) -> ResumoDeInsistencia:
    """Campos perguntados em mais de um turno da mesma conversa.

    O criterio e por **campo**, e nao por frase. Comparar o texto das perguntas
    pegaria so repeticao literal, e a reformulacao passaria: em `compra-14` o
    turno 1 pergunta "para eu montar boas opcoes [...] voce tem alguma regiao
    ou bairro de preferencia?" e o turno 0 pergunta a mesma coisa sem o
    prefixo. Sao a mesma pergunta com textos diferentes.

    O preco desta escolha: dois campos distintos numa frase so contam como duas
    perguntas, e uma reformulacao que troque a palavra-chave escapa. Herda os
    erros de `campos_perguntados`, que sao os do proxy da TEC-210.
    """
    por_conversa: dict[tuple[str, str], list[int]] = defaultdict(list)
    conversas: set[str] = set()
    for pergunta in perguntas:
        conversas.add(pergunta.conversa_id)
        for campo in pergunta.campos:
            por_conversa[(pergunta.conversa_id, campo)].append(pergunta.indice)

    achadas = [
        Insistencia(conversa_id=conversa, campo=campo, turnos=tuple(sorted(turnos)))
        for (conversa, campo), turnos in por_conversa.items()
        if len(turnos) > 1
    ]
    achadas.sort(key=lambda i: (-len(i.turnos), i.conversa_id, i.campo))
    return ResumoDeInsistencia(conversas=len(conversas), insistencias=achadas)


def sem_mecanismo(nome: str, motivo: str) -> ResultadoDaMetrica:
    """Metrica declarada que ainda nao tem o que medir.

    Nunca verde: um slot que reporta verde sem medir nada some do radar e
    finge cobertura que nao existe. E nunca bloqueia: um estado sem mecanismo
    que barrasse merge deixaria o gate permanentemente vermelho, e um gate
    sempre vermelho e desligado em uma semana.
    """
    return ResultadoDaMetrica(
        nome=nome, faixa=Faixa.SEM_MECANISMO, acertos=None, total=None, detalhe=motivo
    )


def bloqueia(metricas: Sequence[ResultadoDaMetrica]) -> bool:
    return any(metrica.faixa is Faixa.VERMELHO for metrica in metricas)


@dataclass(frozen=True)
class ExtracaoObservada:
    """Um turno anotado, com o que se esperava e o que veio.

    `esperado` sao os campos que o corpus anotou para este turno; `obtido` e o
    `Extracao.preenchidos()` do que o modelo devolveu. Os dois sao dicionarios
    de nome de campo para valor.
    """

    conversa_id: str
    indice: int
    esperado: dict[str, Any]
    obtido: dict[str, Any]


def eh_negativo(observada: ExtracaoObservada) -> bool:
    """O criterio de "turno negativo", extraido para nao divergir em silencio.

    `resumo_de_negativos` (aqui) e `_positivas_e_negativas`
    (`evals/test_acuracia_de_intencao.py`) precisam do mesmo criterio: um e o
    gate que decide se sobrou amostra para medir, o outro e o diagnostico que
    conta invencao. Cada um com sua propria expressao (`== {}` num lado,
    `!= {}` no outro) e o mesmo furo que motivou extrair `campos_a_gravar` para
    o eval nao divergir de producao, e que matou `faixa_de_catastrofe` no PR
    #10: duas formulas do mesmo criterio divergem, e a divergencia so aparece
    na borda, sem teste para acusar.
    """
    return observada.esperado == {}


@dataclass(frozen=True)
class ResumoDeNegativos:
    """Quantos turnos negativos entraram na medicao, e quanto se inventou neles.

    Nao carrega faixa: e diagnostico, como `ResumoDeConfianca`. Quem bloqueia
    e `precisao_da_extracao`, que ja conta a invencao no denominador.

    `turnos` precisa existir separado de `com_invencao` porque turno negativo
    limpo nao gera discrepancia nenhuma: sem este numero, o relatorio nao teria
    como dizer se "uma invencao" saiu de dois turnos medidos ou de trinta e
    nove.
    """

    turnos: int
    com_invencao: int
    campos_inventados: int


def resumo_de_negativos(observadas: Sequence[ExtracaoObservada]) -> ResumoDeNegativos:
    """Turno negativo e o que tem `esperado` vazio -- anotado por completo, e o
    completo e nada."""
    negativas = [observada for observada in observadas if eh_negativo(observada)]
    return ResumoDeNegativos(
        turnos=len(negativas),
        com_invencao=sum(1 for observada in negativas if observada.obtido),
        campos_inventados=sum(len(observada.obtido) for observada in negativas),
    )


@dataclass(frozen=True)
class Discrepancia:
    """Um campo que nao casou, com o endereco de onde arrumar.

    `tipo` diz de quem e o problema, e essa distincao e a razao de existir
    desta funcao:

    - `extra`  -- o modelo extraiu, o corpus nao anotou. Acusa a **medicao**:
                  pode ser invencao, mas tambem pode ser extracao correta de
                  campo que ninguem anotou, e no denominador de uniao as duas
                  descontam igual.
    - `faltou` -- o corpus anotou, o modelo nao devolveu. Acusa o **modelo** ou
                  o prompt.
    - `divergiu` -- veio nos dois, com valores diferentes.

    `conversa_id` e `indice` existem para quem for anotar nao precisar de outra
    execucao paga so para descobrir *onde* faltava anotacao.

    `esperado` e `obtido` sao os valores **crus** -- como o corpus anotou e
    como o modelo devolveu --, antes de `_comparavel`. Eles existem porque
    endereco sozinho nao diagnostica `divergiu`: saber que `regiao` divergiu em
    `compra-13[0]` nao diz se o modelo errou a regiao ou se as duas formas so
    nao casaram, e essas duas causas pedem cards opostos. A baseline de
    30/08/2026 (TEC-247) parou exatamente ai -- sete `divergiu` em `regiao`,
    nenhum valor registrado, e a hipotese mais forte (acento) sem como ser
    confirmada sem pagar a execucao de novo.

    Crus de proposito, e nao normalizados: quem le a lista ja sabe que
    `_comparavel` rodou e **nao** reconciliou os dois -- e o que significa
    estar nesta lista --, entao a forma comparada nao acrescenta nada. A crua
    acrescenta: e nela que "saude" contra "Saude" com acento, ou um espaco
    sobrando, ficam visiveis.

    `None` nos dois campos e "este lado nao tinha valor", sem ambiguidade: o
    corpus recusa anotacao com valor nulo (`_turno_de`, `corpus.py`) e
    `preenchidos()` nunca devolve `None`. Entao `faltou` tem `obtido=None`,
    `extra` tem `esperado=None`, e `divergiu` tem os dois preenchidos.
    """

    conversa_id: str
    indice: int
    campo: str
    tipo: Literal["extra", "faltou", "divergiu"]
    esperado: Any = None
    obtido: Any = None


def _comparavel(campo: str, valor: Any) -> Any:
    """Normaliza para comparar anotacao de YAML com valor vindo do parse.

    Recebe o nome do campo porque `regiao` tem contrato de forma proprio
    (TEC-241) e os outros textos nao: caixa e espaco nunca foram erro do
    modelo, mas preposicao e ruido de referencia so sao ruido em toponimo.
    Aplicar `normalizar_regiao` a todo texto faria um campo futuro herdar uma
    regra pensada para outra coisa.

    A regra de forma e importada de `schemas.py`, e nao reescrita aqui: e a
    MESMA que `extrair` aplica antes de gravar, e duas copias divergiriam sem
    nenhum teste acusar.

    Preco vem do YAML como `int` e do parse como `Decimal`, e a mesma
    quantidade de CENTAVOS nos dois tipos tem de contar acerto: 60000000 e
    Decimal("60000000.00") sao os mesmos R$ 600.000. (A chave e `_centavos`
    desde a TEC-146 -- o exemplo anterior falava em `600000` como se fosse o
    preco, que sob esta chave seriam R$ 6.000.)
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return normalizar_regiao(valor) if campo == "regiao" else valor.strip().casefold()
    if isinstance(valor, int | float | Decimal):
        return Decimal(str(valor))
    return valor


def precisao_da_extracao(observadas: Sequence[ExtracaoObservada]) -> ResultadoDaMetrica:
    """Precisao de campo, punindo os dois lados da conta.

    O denominador e a **uniao** dos campos esperados com os obtidos, por turno.
    Isso e o que torna a metrica honesta nas duas direcoes:

    - So o esperado no denominador daria 100% a um modelo que acerta os campos
      anotados e inventa outros quatro.
    - So o obtido daria 100% a um modelo que nunca extrai nada -- o mesmo furo
      que a TEC-233 encontrou em corpus so-positivo, onde um moderador que
      bloqueia tudo passa.

    Turno sem anotacao (`campos` ausente no corpus) nao chega aqui: quem filtra
    e o runner, porque um turno nao anotado nao tem verdade contra a qual
    comparar.
    """
    acertos = 0
    total = 0
    for observada in observadas:
        nomes = set(observada.esperado) | set(observada.obtido)
        total += len(nomes)
        acertos += sum(
            1
            for nome in nomes
            if nome in observada.esperado
            and nome in observada.obtido
            and _comparavel(nome, observada.esperado[nome])
            == _comparavel(nome, observada.obtido[nome])
        )
    faixa = faixa_de(acertos, total, piso=PISO_DE_PRECISAO_DA_EXTRACAO_PCT)
    return ResultadoDaMetrica(
        nome="precisao da extracao",
        faixa=faixa,
        acertos=acertos,
        total=total,
        detalhe=_detalhe(
            acertos, total, f"alvo {ALVO_PCT}%, piso {PISO_DE_PRECISAO_DA_EXTRACAO_PCT}%"
        ),
    )


@dataclass(frozen=True)
class DispersaoEntreExecucoes:
    """Quanto duas execucoes do MESMO codigo ja diferiram, medido.

    Nao e derivado de nada que roda: e resultado de experimento, e so muda
    quando alguem medir de novo. Mora aqui, num lugar so, para nao ser
    transcrito a mao na prosa de tres arquivos -- a licao da TEC-243.
    """

    data: str
    uniao_pp: float
    base_fixa_pp: float


# Medida pela TEC-253 sobre as execucoes de 30/08/2026 das 17:08 e 19:51 UTC:
# prompt, schema, corpus, regua e modelo identicos, e mesmo assim a metrica de
# uniao deu 91,8% e 86,1%. Sobre a base fixa as mesmas duas execucoes deram
# 92,7% e 90,6%.
#
# Duas execucoes nao sao distribuicao: isto e a maior diferenca observada, nao
# a dispersao real, e o limite superior continua desconhecido. Use como piso do
# que o gate NAO distingue, nunca como intervalo de confianca.
#
# **O par de 31/08/2026 deu 0,0, e o numero NAO baixou.** As execucoes das
# 11:46 e 13:19 -- mesmo codigo, mesma regua de 147 turnos -- deram 89/98 as
# duas, identicas. Baixar para 0,0 diria que o gate resolve efeitos
# arbitrariamente pequenos, e isso e falso: duas execucoes concordarem uma vez
# nao e ausencia de dispersao.
#
# A leitura que os tres pares sustentam: a dispersao **nao e propriedade fixa
# da metrica**, e sim funcao de quanto o modelo inventa naquela execucao. O par
# que deu 5,7 teve `extra` indo de 1 para 5; o que deu 0,0 teve `extra` em 1
# nas duas. Quando a invencao e baixa e estavel, as execucoes concordam; quando
# ela oscila, a metrica oscila junto -- e o denominador de uniao amplifica.
# Por isso o numero conservador fica: ele diz o que o gate nao distingue no
# pior caso observado, que e o unico caso em que a pergunta importa.
DISPERSAO_MEDIDA = DispersaoEntreExecucoes(data="30/08/2026", uniao_pp=5.7, base_fixa_pp=2.1)


@dataclass(frozen=True)
class DecomposicaoDaExtracao:
    """A conta de `precisao_da_extracao` aberta em parcelas que se movem
    diferente.

    A metrica que trava usa denominador de **uniao** (`esperado | obtido`), e
    isso e certo: sem contar o inventado, um modelo que acerta o anotado e
    inventa mais quatro campos tiraria 100%. O preco e que ela soma numa razao
    so duas coisas de natureza oposta:

    - `faltou` e `divergiu` medem o **defeito**, e sao estaveis entre
      execucoes -- nas quatro execucoes de sonnet-5 de 30/08/2026, `faltou`
      deu 8, 8, 8 e 7.
    - `extra` e a parte que **oscila** (1, 3, 5 e 7 nas mesmas quatro), e cada
      campo inventado desconta duas vezes: deixa de ser acerto **e** infla o
      denominador.

    Por isso a mesma arvore pode sair VERDE ou AMARELO dependendo da hora, e
    por isso esta decomposicao existe: `anotados` e constante por construcao
    (e o corpus), entao `acertos/anotados` isola o defeito do ruido.

    Isto e diagnostico, como `ResumoDeNegativos` e `ResumoDeConfianca`. Quem
    bloqueia continua sendo `precisao_da_extracao`, com o mesmo piso: a TEC-253
    mediu o instrumento, nao mudou o que ele cobra.
    """

    anotados: int
    acertos: int
    faltou: int
    divergiu: int
    extra: int

    @property
    def taxa_sobre_base_fixa(self) -> float | None:
        """`None` quando nao ha campo anotado -- a razao nao existiria."""
        return self.acertos / self.anotados if self.anotados else None


def decomposicao_da_extracao(
    observadas: Sequence[ExtracaoObservada],
) -> DecomposicaoDaExtracao:
    """Mesma varredura de `precisao_da_extracao`, aberta por tipo.

    Refaz o laco em vez de somar `discrepancias_da_extracao`, e isso e
    deliberado: `acertos` aqui tem de ser **o mesmo** numero que a metrica que
    trava publica, e a unica forma de garantir isso e aplicar `_comparavel` do
    mesmo jeito. Um teste amarra as duas contas (`anotados` = acertos + faltou
    + divergiu, e uniao = anotados + extra), para a divergencia aparecer na
    suite e nao numa execucao paga.
    """
    anotados = acertos = faltou = divergiu = extra = 0
    for observada in observadas:
        anotados += len(observada.esperado)
        for nome in set(observada.esperado) | set(observada.obtido):
            if nome not in observada.esperado:
                extra += 1
            elif nome not in observada.obtido:
                faltou += 1
            elif _comparavel(nome, observada.esperado[nome]) == _comparavel(
                nome, observada.obtido[nome]
            ):
                acertos += 1
            else:
                divergiu += 1
    return DecomposicaoDaExtracao(
        anotados=anotados, acertos=acertos, faltou=faltou, divergiu=divergiu, extra=extra
    )


# Os campos que o corpus pode anotar e que `Extracao` carrega. Derivado da
# dataclass, e nao escrito a mao: um campo novo em `Extracao` entra aqui
# sozinho, e a alternativa -- uma lista literal -- envelheceria calada no dia
# em que alguem acrescentasse um campo (a licao da TEC-243, aplicada a codigo).
CAMPOS_DA_EXTRACAO = frozenset(campo.name for campo in fields(Extracao))


@dataclass(frozen=True)
class EstadoDaConversa:
    """O que a conversa deixou gravado, contra o que ela deveria ter deixado.

    `obtido` e o `estado_acumulado` do runner **filtrado** aos campos de
    extracao: ele vem de `campos_a_gravar`, a mesma funcao que `gravar_estado`
    usa em producao, e carrega tambem `intencao`, que nao e campo de extracao e
    nao tem anotacao contra a qual comparar.

    `esperado` e a anotacao do corpus acumulada com a mesma regra de "mais novo
    vence".
    """

    conversa_id: str
    esperado: dict[str, Any]
    obtido: dict[str, Any]


@dataclass(frozen=True)
class ResumoDaExtracaoEfetiva:
    """A extracao medida como producao a experimenta, e por que ela difere.

    `precisao_da_extracao` compara **turno a turno**: `obtido` e o
    `preenchidos()` daquele turno. Producao nao funciona assim -- `None` nao
    apaga (ver `campos_a_gravar`), entao o estado carrega o que turnos
    anteriores gravaram. Quando o lead diz *"qual o valor do condominio dessa
    cobertura?"*, o modelo devolve `null` para `tipo_imovel` -- corretamente,
    porque a regra do prompt manda extrair so o que a fala **afirma**, e essa
    pergunta pressupoe em vez de afirmar. A metrica turno a turno conta erro;
    o estado ja tem `APARTAMENTO` do primeiro turno e nao muda.

    Medido em 30/08/2026 (TEC-252): dos oito campos que a metrica turno a
    turno deu como `faltou`, **seis eram reafirmacao de valor que o estado ja
    tinha**. O corpus tem sete turnos de reafirmacao e o modelo "falha" em seis
    deles, sem nenhuma consequencia para o lead.

    Isto e diagnostico, e nao entra em `bloqueia`. Promove-lo a metrica que
    trava e decisao separada: exigiria piso proprio e medido, e o piso de
    `precisao_da_extracao` foi calibrado contra outra conta.

    E o espelho do que `acuracia_efetiva` faz para a intencao -- medir o que
    producao roteia, e nao o palpite cru.
    """

    conversas: int
    acertos: int
    total: int
    divergencias: list["DivergenciaDeEstado"]

    @property
    def taxa(self) -> float | None:
        return self.acertos / self.total if self.total else None


@dataclass(frozen=True)
class DivergenciaDeEstado:
    """Um campo em que o estado final da conversa nao bateu com a anotacao.

    `tipo` segue `Discrepancia`, e pelo mesmo motivo: `faltou` acusa o modelo,
    `extra` acusa a medicao antes do modelo, `divergiu` sao os dois com valores
    diferentes.
    """

    conversa_id: str
    campo: str
    tipo: Literal["extra", "faltou", "divergiu"]
    esperado: Any = None
    obtido: Any = None


def precisao_efetiva_da_extracao(
    estados: Sequence[EstadoDaConversa],
) -> ResumoDaExtracaoEfetiva:
    """Compara o estado final de cada conversa, nao cada turno.

    Denominador de uniao, como em `precisao_da_extracao` e pelo mesmo motivo:
    sem contar o inventado, um estado que acerta o anotado e carrega tres
    campos que ninguem anotou pontuaria igual a um limpo.

    Uma comparacao por conversa, e nao uma por turno: comparar o acumulado a
    cada turno contaria o mesmo campo tantas vezes quantos turnos a conversa
    tem, e daria peso maior a conversa longa. O preco e que um campo gravado
    certo e depois sobrescrito errado aparece so pelo valor final -- que e,
    de todo modo, o que o handoff e o lead scoring vao ler.
    """
    acertos = total = 0
    divergencias: list[DivergenciaDeEstado] = []
    for estado in estados:
        for campo in sorted(set(estado.esperado) | set(estado.obtido)):
            total += 1
            if campo not in estado.esperado:
                divergencias.append(
                    DivergenciaDeEstado(
                        conversa_id=estado.conversa_id,
                        campo=campo,
                        tipo="extra",
                        obtido=estado.obtido[campo],
                    )
                )
            elif campo not in estado.obtido:
                divergencias.append(
                    DivergenciaDeEstado(
                        conversa_id=estado.conversa_id,
                        campo=campo,
                        tipo="faltou",
                        esperado=estado.esperado[campo],
                    )
                )
            elif _comparavel(campo, estado.esperado[campo]) == _comparavel(
                campo, estado.obtido[campo]
            ):
                acertos += 1
            else:
                divergencias.append(
                    DivergenciaDeEstado(
                        conversa_id=estado.conversa_id,
                        campo=campo,
                        tipo="divergiu",
                        esperado=estado.esperado[campo],
                        obtido=estado.obtido[campo],
                    )
                )
    return ResumoDaExtracaoEfetiva(
        conversas=len(estados), acertos=acertos, total=total, divergencias=divergencias
    )


def discrepancias_da_extracao(
    observadas: Sequence[ExtracaoObservada],
) -> list[Discrepancia]:
    """Decompoe o que `precisao_da_extracao` conta como erro, campo a campo.

    Diagnostico, nunca gate: nao devolve faixa e nao entra em `bloqueia`. O
    numero da metrica sozinho nao diz se o corpus mede errado ou se o modelo
    extrai mal, e essas duas causas pedem cards diferentes.

    Vale a invariante `acertos + len(discrepancias) == total` contra a mesma
    sequencia de observadas -- ha teste guardando isso. Ela existe porque as
    duas funcoes derivam do mesmo conjunto (a uniao de esperado com obtido), e
    se alguem mudar a formula de uma sem mudar a outra o relatorio passa a
    mentir em silencio em vez de quebrar.

    A ordem acompanha os turnos observados, e dentro do turno e alfabetica por
    campo: quem le a lista le de cima para baixo, seguindo a conversa, e a
    ordem nao pode depender da iteracao de um `set`.
    """
    achadas: list[Discrepancia] = []
    for observada in observadas:
        for campo in sorted(set(observada.esperado) | set(observada.obtido)):
            no_esperado = campo in observada.esperado
            no_obtido = campo in observada.obtido
            if no_esperado and no_obtido:
                if _comparavel(campo, observada.esperado[campo]) == _comparavel(
                    campo, observada.obtido[campo]
                ):
                    continue
                tipo: Literal["extra", "faltou", "divergiu"] = "divergiu"
            elif no_obtido:
                tipo = "extra"
            else:
                tipo = "faltou"
            achadas.append(
                Discrepancia(
                    conversa_id=observada.conversa_id,
                    indice=observada.indice,
                    campo=campo,
                    tipo=tipo,
                    esperado=observada.esperado.get(campo),
                    obtido=observada.obtido.get(campo),
                )
            )
    return achadas
