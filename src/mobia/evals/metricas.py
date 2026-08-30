from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import Intencao, normalizar_regiao

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
    """

    conversa_id: str
    indice: int
    campo: str
    tipo: Literal["extra", "faltou", "divergiu"]


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

    Preco vem do YAML como `int` e do parse como `Decimal`, e 600000 e
    Decimal("600000.00") sao o mesmo preco.
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
                )
            )
    return achadas
