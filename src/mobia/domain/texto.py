"""A dobra de texto que a busca estruturada compara.

TEC-158, D6. Funcao pura: sem banco, sem rede, sem `Settings`.

**Mora fora de `catalogo/` e de `agente/` porque os dois a usam.** A
importacao do catalogo grava `bairro_busca` com ela; `normalizar_regiao`
dobra a fala do lead com ela. Qualquer das duas casas obrigaria um dominio a
importar o outro -- e a D2 desta card decidiu que `catalogo` nao importa
`agente`, sendo a seta contraria igualmente errada.

**Faz caixa e acento, e nada mais.** Os prefixos de referencia de
`normalizar_regiao` (`perto da `, `estacao `, `avenida `) sao ruido de FALA:
aplicados a nome de bairro comeriam o nome de um bairro chamado "Estacao".
"""

import unicodedata


def dobrar(texto: str) -> str:
    """A forma comparavel de um texto: sem acento, em caixa dobrada.

    NFD separa o diacritico do caractere base e `combining` identifica o que
    sobra para descartar. Pega cedilha junto: "aclimacao" com til e cedilha
    decompoe nos dois, e os dois somem. O corpo desta funcao veio do
    `_sem_acento` que morava em `agente/schemas.py`, e a medicao que o
    justifica esta na docstring de `normalizar_regiao`: a TEC-248 mediu o
    modelo devolvendo `saude` COM acento e `butanta` SEM, na mesma execucao.

    `casefold` e nao `lower`: dobra mais que minusculas, e comparacao de
    igualdade e exatamente o caso de uso dele.

    Espaco interno e colapsado: "vila  madalena" e "vila madalena" sao o
    mesmo bairro, e um arquivo com dois espacos nao pode deixar a linha
    inalcancavel pela busca.
    """
    sem_acento = "".join(
        caractere
        for caractere in unicodedata.normalize("NFD", texto)
        if not unicodedata.combining(caractere)
    )
    return " ".join(sem_acento.split()).casefold()
