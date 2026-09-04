"""A regua da cadencia de reengajamento: quem esta devido, e de qual tentativa.

TEC-183, RN-13.1. Pura de proposito: sem I/O, sem banco, sem chamada ao
modelo -- mesma forma de `score.py`, `temperatura.py` e `gatilhos.py`. Quem
consulta o banco e decide gravar e o repositorio; aqui so se faz a conta.

**Os deslocamentos sao contados desde a ancora, e nao encadeados.** A RN-13.1
diz "contada a partir da ultima mensagem do lead", e a CA-13.1 confirma com
numero: parou as 18h, follow-up as 20h. Entao a tentativa N vence em
`ultima_fala + CADENCIA[temperatura][N-1]`, e nao "24h depois do follow-up
anterior". A diferenca e observavel: encadeando, um atraso na varredura
empurraria toda a cauda; ancorando, um disparo atrasado nao desloca os
seguintes.

**Constantes de modulo, e nao configuracao.** A card pede intervalos
ajustaveis sem deploy; isso e um subsistema (persistir, autorizar, invalidar
cache) e pertence ao epico de configuracao (RF-19), exatamente como a TEC-150
decidiu para os pesos do score. Lacuna declarada no desenho.
"""

from datetime import datetime, timedelta

from mobia.domain.context.temperatura import Temperatura

# A tabela da RN-13.1, literal. A ordem dentro de cada tupla e a ordem das
# tentativas, e o indice N-1 e o deslocamento da tentativa N.
CADENCIA: dict[Temperatura, tuple[timedelta, ...]] = {
    Temperatura.QUENTE: (
        timedelta(hours=2),
        timedelta(hours=24),
        timedelta(days=3),
        timedelta(days=7),
    ),
    Temperatura.MORNO: (
        timedelta(hours=24),
        timedelta(days=4),
        timedelta(days=10),
    ),
    Temperatura.FRIO: (
        timedelta(days=3),
        timedelta(days=14),
    ),
}

# O corte barato da varredura: nada abaixo disto pode estar devido em
# temperatura nenhuma, entao a consulta descarta o lead sem olhar mais nada.
#
# Derivado e nao escrito a mao de proposito. Escrito a mao, seria uma segunda
# fonte para um fato que `CADENCIA` ja guarda -- e quem mexesse na tabela
# deixaria o corte para tras em silencio, filtrando leads que agora estariam
# devidos mais cedo.
INTERVALO_MINIMO: timedelta = min(intervalos[0] for intervalos in CADENCIA.values())


def tentativa_devida(
    *,
    temperatura: Temperatura,
    ultima_fala: datetime,
    ja_disparada: int,
    agora: datetime,
) -> int | None:
    """A MAIOR tentativa vencida que ainda nao disparou. `None` se nao ha.

    **Devolve a maior vencida, e nao a proxima.** Um lead QUENTE calado ha dez
    dias tem as quatro vencidas ao mesmo tempo; devolvendo "a proxima", ele
    receberia uma por varredura -- quatro follow-ups em vinte minutos, para
    alguem que sumiu ha dez dias. As tres que passaram nao sao "perdidas": os
    deslocamentos sao absolutos desde a ancora, entao o momento de mandar a de
    +2h acabou ha dez dias, e manda-la agora entregaria uma mensagem cujo
    pressuposto de tempo ja e falso.

    **`ja_disparada` e o MAIOR numero de tentativa ja gravado sob esta ancora,
    e nao uma contagem.** Com contagem, o lead do exemplo receberia a 4
    (contagem 0) e, na varredura seguinte, a regua acharia que so uma foi feita
    e dispararia a 2 -- refazendo para tras. Com o maximo, a 4 fecha a cadencia
    inteira. A diferenca so aparece quando ha salto.

    **Zero e o valor de "nunca disparou sob esta ancora"**, e e o que o
    repositorio devolve quando nao ha linha -- a numeracao das tentativas e
    1-based.

    **A borda e inclusiva (`>=`).** No instante exato do deslocamento a
    tentativa vence; com `>` um disparo escorregaria para a varredura seguinte
    por um microssegundo.

    Tudo keyword-only: `ultima_fala` e `agora` sao dois `datetime` adjacentes,
    e trocar a ordem nao levanta, nao e erro de tipo, nao e visivel ao mypy, e
    devolve a tentativa errada em silencio. Mesma razao das duas contagens de
    `calcular_score` e dos dois flags de `temperatura_de`.

    **Invariante: os intervalos em cada tupla sao estritamente crescentes.**
    A descida pela tabela so acha a tentativa MAIOR porque nenhuma tentativa
    anterior e mais vencida. Se a ordem quebra, a funcao silenciosamente devolve
    a errada.
    """
    decorrido = agora - ultima_fala
    for numero in range(len(CADENCIA[temperatura]), ja_disparada, -1):
        if decorrido >= CADENCIA[temperatura][numero - 1]:
            return numero
    return None
