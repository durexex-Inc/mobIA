"""Telefone brasileiro: achar na fala do lead e levar a uma forma so. TEC-129, D2.

**Deterministico de proposito.** A alternativa era um campo `telefone` na
extracao do classificador, e ela custaria prompt e schema -- que o teste da
margem do orcamento vigia -- em troca de uma extracao que muda de uma chamada
para outra. Um vinculo de identidade que muda de uma chamada para outra nao e
vinculo.

**A forma canonica e a do `wa_id` da Meta, com o 9**: so digitos, com o `55`.
Celular tem 13 digitos, fixo tem 12. A Meta entrega parte dos celulares
brasileiros SEM o 9 -- `554899990000` --, e e por isso que `normalizar`
insere o 9 em celular de oito digitos: e a mesma regra que faz o `wa_id` e o
numero digitado no site se encontrarem.

So numero brasileiro. Estrangeiro nao e reconhecido, e isso e limite declarado
da spec, nao descuido.
"""

import re

# DDDs em uso no Brasil. Sem esta lista, qualquer sequencia de dez digitos
# comecando por 20, 23, 25... viraria telefone.
_DDDS = frozenset(
    {
        "11", "12", "13", "14", "15", "16", "17", "18", "19",
        "21", "22", "24", "27", "28",
        "31", "32", "33", "34", "35", "37", "38",
        "41", "42", "43", "44", "45", "46", "47", "48", "49",
        "51", "53", "54", "55",
        "61", "62", "63", "64", "65", "66", "67", "68", "69",
        "71", "73", "74", "75", "77", "79",
        "81", "82", "83", "84", "85", "86", "87", "88", "89",
        "91", "92", "93", "94", "95", "96", "97", "98", "99",
    }
)  # fmt: skip

# `(?<!\d)` e `(?!\d)` impedem casar um pedaco de uma corrida maior de digitos
# -- sem eles, os onze primeiros digitos de um numero de protocolo virariam
# telefone. O separador entre os blocos e UM de espaco, ponto ou hifen, ou
# nenhum; virgula nao entra, porque e o separador decimal do preco.
#
# Duas formas comuns que a primeira versao recusava (revisao final da TEC-129):
# o 9 separado do resto do celular -- `(48) 9 9999-0000` -- e o zero de tronco
# antes do DDD -- `(048) 99999-0000`. O separador depois do primeiro digito so
# e admitido quando esse digito e 9, que e o unico caso em que ele e o 9 do
# celular; o zero entra opcional aqui, e quem decide se ele e tronco e
# `normalizar` (ver `_TRONCO`).
_CANDIDATO = re.compile(
    r"(?<!\d)(?:\+?55[\s.-]?)?\(?0?\d{2}\)?[\s.-]?(?:9[\s.-]?\d{4}|\d{4,5})[\s.-]?\d{4}(?!\d)"
)

# O zero de tronco so e reconhecido quando a mascara o poe junto do DDD --
# entre parenteses, ou seguido de separador. Sem mascara, onze digitos
# comecando por zero sao CPF cru tanto quanto telefone, e descartar o zero ali
# abriria um falso positivo novo: `01234567890` viraria o fixo `(12) 3456-7890`.
_TRONCO = re.compile(r"^\s*(?:\(0\d{2}\)|0\d{2}[\s.-])")


def normalizar(bruto: str) -> str | None:
    """A forma canonica do telefone, ou `None` se nao for telefone brasileiro."""
    digitos = re.sub(r"\D", "", bruto)
    if _TRONCO.match(bruto):
        digitos = digitos[1:]
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        nacional = digitos[2:]
    elif len(digitos) in (10, 11):
        nacional = digitos
    else:
        return None

    ddd, assinante = nacional[:2], nacional[2:]
    if ddd not in _DDDS:
        return None
    if len(assinante) == 9:
        # Nove digitos so existem em celular, e celular comeca por 9.
        if not assinante.startswith("9"):
            return None
    elif assinante[0] in "6789":
        # Celular de oito digitos: o `wa_id` sem o 9, ou um numero anotado
        # antes de 2016. Os dois ganham o 9.
        assinante = "9" + assinante
    elif assinante[0] not in "2345":
        # Fixo comeca de 2 a 5; o resto nao e numero em uso.
        return None
    return "55" + ddd + assinante


def grafias_do_wa_id(canonico: str) -> tuple[str, ...]:
    """As formas em que a Meta pode entregar este numero. TEC-203.

    A Meta entrega parte dos celulares brasileiros sem o 9 (ver a docstring do
    modulo); a busca por telefone precisa das duas para achar o `wa_id`.
    """
    if len(canonico) == 13 and canonico[4] == "9":
        return (canonico, canonico[:4] + canonico[5:])
    return (canonico,)


def extrair_telefone(texto: str) -> str | None:
    """O telefone da fala, se houver exatamente um.

    **Dois telefones diferentes devolvem `None`.** Nao ha como saber qual e o da
    pessoa -- "o meu e X, o da minha esposa e Y" --, e vincular o errado poe o
    que ela disse no contexto do WhatsApp de outra pessoa. O mesmo numero
    repetido conta como um.
    """
    encontrados = {
        canonico
        for candidato in _CANDIDATO.finditer(texto)
        if (canonico := normalizar(candidato.group())) is not None
    }
    if len(encontrados) != 1:
        return None
    return encontrados.pop()
