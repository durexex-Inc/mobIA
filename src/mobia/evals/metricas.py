from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import Intencao

# Alvo do card. Abaixo do piso o merge e barrado; entre os dois, avisa.
ALVO_PCT = 90
PISO_DE_BLOQUEIO_PCT = 84

# O piso da extracao vem do card (RF-05, secao 4.4 do SRS): 85%. Diferente do
# `PISO_DE_BLOQUEIO_PCT` de intencao, que e 84.
PISO_DE_PRECISAO_DA_EXTRACAO_PCT = 85

# Abaixo deste numero de turnos um unico turno vale mais de 0,8% e a faixa
# amarela deixa de absorver o ruido entre execucoes.
PISO_DE_TURNOS = 120

# Piso de anotacao, irmao do PISO_DE_TURNOS. Sem ele, anotar tres turnos
# faceis daria precisao alta num corpus que nao mede nada -- o mesmo furo do
# corpus so-positivo, na outra direcao.
PISO_DE_TURNOS_ANOTADOS = 30

# Quantas conversas a execucao pode perder para falha de infraestrutura antes
# de deixar de valer como medida.
#
# O numero vem do corpus e do piso, nao do gosto. Hoje sao 50 conversas e 136
# turnos, e a conversa mais longa tem 3 turnos; a folga do piso e 136 - 120 =
# 16 turnos. Cinco conversas abandonadas custam no pior caso 5 x 3 = 15
# turnos: uma folga de um turno sobra. O teto de 5 continua valido -- abandono
# nenhum consegue furar o piso -- porque com seis, o pior caso ja seria 118
# turnos, e os dois limites passariam a reprovar a mesma execucao por motivos
# diferentes, com a mensagem decidida por quem for verificado primeiro.
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


def _comparavel(valor: Any) -> Any:
    """Normaliza para comparar anotacao de YAML com valor vindo do parse.

    `regiao` e texto livre escrito a mao no corpus: caixa e espaco nao sao erro
    do modelo. Preco vem do YAML como `int` e do parse como `Decimal`, e
    600000 e Decimal("600000.00") sao o mesmo preco.
    """
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, str):
        return valor.strip().casefold()
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
            and _comparavel(observada.esperado[nome]) == _comparavel(observada.obtido[nome])
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
