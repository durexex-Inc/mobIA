"""Nome e telefone do lead nao saem para o provedor. TEC-381, RNF-23.

**Irreversivel, com marcador fixo** (D2, decisao do Eduardo). O modelo recebe
`[nome do lead]` e `[telefone do lead]` e nunca o original, e nao ha tabela de
volta: o agente simplesmente nao chama o lead pelo nome. A RNF-23 pede
pseudonimo "sempre que nao forem necessarios a resposta", e nenhuma resposta do
agente precisa deles -- o contato do lead e o proprio canal.

**So em transito.** Nada aqui toca o banco: o vinculo de telefone da TEC-129 le
o numero da fala gravada, e o corretor precisa do contato real. Quem chama e
quem esta a um passo do provedor (`context/montagem.py::_texto_da`, a
moderacao de entrada).

**Nome so em frase explicita** (D3, decisao do Eduardo). Sem uma lista de
prenomes, que trocaria bairro por nome (Vitoria, Gloria, Rosa), o nome solto
("Marina aqui") e a assinatura passam -- limite declarado.
"""

import re

from mobia.domain.identidade.telefone import trechos_de_telefone

MARCADOR_DE_NOME = "[nome do lead]"
MARCADOR_DE_TELEFONE = "[telefone do lead]"

_MAIUSCULA = r"[A-ZÀ-Ý][a-zà-ÿ]+"
_QUALQUER = r"[A-Za-zÀ-ÿ]+"
# Sobrenomes: so palavras com maiuscula, com "de", "da", "dos"... entre elas.
# E a maiuscula que para o nome antes do resto da frase: "me chamo Marina e
# procuro casa" termina em "Marina".
_SOBRENOMES = r"(?:[ \t]+(?:d[aeo]s?[ \t]+)?" + _MAIUSCULA + r"){0,3}"

# Depois destas, o que vem e nome mesmo em minuscula: a frase ja o anuncia.
_ANUNCIO_FORTE = r"(?i:\bme chamo|\bmeu nome(?: completo)? (?:é|e))[ \t]+"
# Depois destas, so com maiuscula: "sou o dono do apartamento" nao e nome.
_ANUNCIO_FRACO = (
    r"(?i:\b(?:eu )?sou (?:o|a)|\baqui (?:é|e) (?:o|a)|\bquem fala (?:é|e) (?:o|a))[ \t]+"
)

_NOME_ANUNCIADO = re.compile(
    _ANUNCIO_FORTE + r"(?P<forte>" + _QUALQUER + _SOBRENOMES + r")"
    r"|" + _ANUNCIO_FRACO + r"(?P<fraco>" + _MAIUSCULA + _SOBRENOMES + r")"
)


def pseudonimizar(texto: str) -> str:
    """O texto com o telefone e o nome anunciado trocados pelos marcadores.

    Idempotente: os marcadores nao casam com nenhum dos dois padroes, entao
    pseudonimizar o que ja passou por aqui -- o resumo, que e gerado a partir
    das literais ja pseudonimizadas e volta ao prompt -- nao muda nada.
    """
    trechos: list[tuple[int, int, str]] = [
        (inicio, fim, MARCADOR_DE_TELEFONE) for inicio, fim in trechos_de_telefone(texto)
    ]
    for achado in _NOME_ANUNCIADO.finditer(texto):
        grupo = "forte" if achado.group("forte") is not None else "fraco"
        trechos.append((achado.start(grupo), achado.end(grupo), MARCADOR_DE_NOME))
    if not trechos:
        return texto
    partes = []
    cursor = 0
    for inicio, fim, marcador in sorted(trechos):
        if inicio < cursor:
            # Sobreposicao: o trecho anterior ja cobre este.
            continue
        partes.append(texto[cursor:inicio])
        partes.append(marcador)
        cursor = fim
    partes.append(texto[cursor:])
    return "".join(partes)


# "Oi, [nome do lead]!" -> "Oi!": o marcador antes de pontuacao leva junto a
# virgula e o espaco que o precediam. So com palavra antes (`(?<=\S)`): no
# comeco da frase, "[nome do lead], encontrei" levaria o marcador e deixaria a
# virgula -- ali quem resolve e a regra de baixo.
_NOME_ANTES_DE_PONTUACAO = re.compile(
    r"(?<=\S)[ \t]*,?[ \t]*" + re.escape(MARCADOR_DE_NOME) + r"(?=[,.!?;:])"
)
# "[nome do lead], encontrei..." e qualquer outro lugar: some com a virgula e o
# espaco que o seguiam.
_NOME_EM_OUTRO_LUGAR = re.compile(re.escape(MARCADOR_DE_NOME) + r",?[ \t]*")
_ESPACOS_REPETIDOS = re.compile(r"[ \t]{2,}")


def sem_marcadores(texto: str) -> str:
    """A fala do modelo sem os marcadores que ele tenha copiado do contexto.

    O modelo ve `[nome do lead]` e pode repeti-lo ("Oi, [nome do lead]!"); o
    lead nao pode receber isso. O nome some, e o telefone vira "seu telefone",
    que e o que a frase queria dizer. Mora na fonte da fala (o classificador),
    e nao no envio, porque a mesma fala e gravada e moderada na saida.
    """
    if MARCADOR_DE_NOME not in texto and MARCADOR_DE_TELEFONE not in texto:
        return texto
    texto = _NOME_ANTES_DE_PONTUACAO.sub("", texto)
    texto = _NOME_EM_OUTRO_LUGAR.sub("", texto)
    texto = texto.replace(MARCADOR_DE_TELEFONE, "seu telefone")
    return _ESPACOS_REPETIDOS.sub(" ", texto).strip()
