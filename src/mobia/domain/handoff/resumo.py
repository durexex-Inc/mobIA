"""O resumo de handoff: os seis blocos, o validador e o redator.

TEC-175, RF-15.
"""

# RN-15.2. O numero mora aqui e so aqui -- quem precisa dele importa a
# constante, para nao existir uma segunda copia livre para divergir.
LIMITE_DE_CARACTERES = 1500

# Os seis blocos da RN-15.1, como marcadores LITERAIS e nao como instrucao em
# prosa. Sem marcador fixo, o primeiro cenario do Gherkin -- "contem os seis
# blocos na ordem definida" -- nao e testavel: vira opiniao sobre um texto
# corrido. O custo e um resumo com cara de formulario; o ganho e um criterio
# de aceite que e asercao, e nao leitura.
MARCADORES = (
    "## Quem e o lead",
    "## O que procura",
    "## Score e temperatura",
    "## Imoveis apresentados",
    "## Pontos de atencao",
    "## Proxima acao",
)


class ResumoDeHandoffInvalido(RuntimeError):
    """A resposta do modelo nao e um resumo utilizavel.

    Mesmo papel do `ResumoInvalido` de `context/resumo.py`: levantar aqui, em
    vez de gravar um resumo manco, e o que da ao chamador a chance de nao
    gravar nada. Um resumo truncado e pior que resumo nenhum -- ele corta o
    fim, e o fim e o bloco da proxima acao, que e o que diz ao corretor o que
    fazer. Ver a D7 do desenho.
    """


def validar(texto: str) -> str:
    """Devolve o texto quando ele e um resumo valido; levanta quando nao e.

    A ordem e conferida por posicao crescente e nao por presenca: seis blocos
    presentes fora de ordem satisfazem "contem os seis" e mesmo assim nao sao
    o que a RN-15.1 pede.
    """
    limpo = texto.strip()
    if not limpo:
        raise ResumoDeHandoffInvalido("resumo vazio ou so com espaco em branco")

    if len(limpo) > LIMITE_DE_CARACTERES:
        raise ResumoDeHandoffInvalido(
            f"resumo acima do limite: {len(limpo)} de {LIMITE_DE_CARACTERES} caracteres"
        )

    posicoes = []
    for marcador in MARCADORES:
        posicao = limpo.find(marcador)
        if posicao < 0:
            raise ResumoDeHandoffInvalido(f"bloco ausente: {marcador!r}")
        posicoes.append(posicao)

    if posicoes != sorted(posicoes):
        raise ResumoDeHandoffInvalido("blocos fora de ordem")

    return limpo
