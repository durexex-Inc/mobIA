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

**`CADENCIA` e o padrao, e a vigente vem da configuracao** (TEC-198). Ate
aquela card isto dizia "constantes de modulo, e nao configuracao", e que
torna-las ajustaveis era do epico de configuracao (RF-19). A TEC-198 as
tornou: o administrador troca os INTERVALOS em `configuracoes_do_agente`, e a
varredura passa a vigente as funcoes abaixo. A QUANTIDADE de tentativas por
temperatura continua sendo a desta tabela -- ela esta no `CASE` SQL de
`repositorio.py`, gerado na importacao do modulo.
"""

from collections.abc import Mapping
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

# O tipo da tabela, com ou sem configuracao. `CADENCIA` acima e o PADRAO desde a
# TEC-198: o administrador troca os INTERVALOS em `configuracoes_do_agente`, e a
# varredura passa a vigente as tres funcoes abaixo. A QUANTIDADE de tentativas
# por temperatura continua sendo a desta tabela (D5 daquele desenho): ela esta
# no `CASE` SQL que `repositorio.py` gera na importacao do modulo.
Cadencia = Mapping[Temperatura, tuple[timedelta, ...]]


def cadencia_de(
    por_nome: Mapping[str, tuple[timedelta, ...]],
) -> dict[Temperatura, tuple[timedelta, ...]]:
    """A cadencia da configuracao, chaveada pelo enum. TEC-198.

    A configuracao a guarda pelo NOME da temperatura porque
    `configuracao/vigente.py` nao pode importar `Temperatura` sem fechar um
    ciclo -- ver a docstring de la. E aqui que o nome volta a ser enum.
    """
    return {Temperatura(nome): intervalos for nome, intervalos in por_nome.items()}


def intervalo_minimo(cadencia: Cadencia) -> timedelta:
    """O corte barato da varredura para ESTA cadencia. TEC-198, D5.

    Calculado a cada varredura, e nao a constante acima: com o primeiro
    intervalo encurtado pelo administrador, o corte antigo esconderia leads
    que ja estao devidos -- o mesmo defeito que o comentario de
    `INTERVALO_MINIMO` descreve para quem escrevesse o corte a mao.
    """
    return min(intervalos[0] for intervalos in cadencia.values())


def tentativa_devida(
    *,
    temperatura: Temperatura,
    ultima_fala: datetime,
    ja_disparada: int,
    agora: datetime,
    cadencia: Cadencia = CADENCIA,
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
    for numero in range(len(cadencia[temperatura]), ja_disparada, -1):
        if decorrido >= cadencia[temperatura][numero - 1]:
            return numero
    return None


def esta_dormente(*, temperatura: Temperatura, ja_disparada: int) -> bool:
    """RN-13.5: o lead esgotou a cadencia e saiu da automacao.

    **E derivado, e nao um estado gravado.** Nao ha coluna `status` em lugar
    nenhum, e esta funcao nao le nem escreve banco: a pergunta e respondida
    pela tabela da RN-13.1 e pelo que `followups` ja guarda. A data e a
    contagem que a card pede da transicao sao o `created_at` e o
    `tentativa_numero` da linha da ultima tentativa. Ver a D1 do desenho.

    **Esta expressao e a negacao exata do corte de candidatura** em
    `repositorio.py` (`ja_disparada < CASE temperatura ... END`). Nao sao duas
    fontes que podem divergir: aquele `CASE` e GERADO a partir de `CADENCIA`
    por `_TETOS_POR_TEMPERATURA`, e esta funcao le o mesmo dict. Quem alongar a
    tabela move os dois. `test_dormente_e_a_negacao_exata_do_corte_de_candidatura`
    prova a metade Python dessa afirmacao -- que esta funcao nao se descola de
    `CADENCIA` --, comparando contra `ja_disparada < len(CADENCIA[temperatura])`
    calculado no proprio teste; ele nao le o `CASE` do SQL, entao nao e garantia
    de que o lado do banco continua igual.

    **`>=` e nao `==`**: se `ja_disparada` um dia puder passar do teto vigente
    sem a ancora se mover -- um lead que esgotasse QUENTE em 4 e so depois
    esfriasse para MORNO, cujo teto e 3 --, `==` o faria deixar de ser
    dormente ao esfriar, o contrario do que a temperatura mais fria significa.
    **Esse caminho e alcancavel, e o `>=` e o que o mantem certo.** Esta
    docstring dizia que nao: que o unico chamador de `registrar_recalculo` era
    `executar_turno`, cuja fala move a ancora. Deixou de ser verdade com a
    TEC-172 (o nao comparecimento, `agendamento/ciclo.py`) e a TEC-194 (a
    edicao manual, `leads/edicao.py`): os dois recalculam sem fala do lead.
    Desde a TEC-385 a cadencia le `temperatura_da_cadencia`, que o nao
    comparecimento nao move; a edicao manual continua podendo esfriar o lead
    sem mover a ancora, e e ai que o `>=` segura.

    **`temperatura` e `Temperatura`, e nao `str | None`.** Lead com
    `temperatura IS NULL` (escreveu antes da TEC-151 e nunca mais falou) fica
    fora do alcance da cadencia: o filtro `IN` da consulta de candidatos
    (`_SELECIONAR_CANDIDATOS`, em `repositorio.py`) ja o exclui antes de
    qualquer chamada a esta funcao. A tipagem recusa a pergunta em vez de
    inventar uma resposta -- lacuna L3 do desenho.
    """
    return ja_disparada >= len(CADENCIA[temperatura])
