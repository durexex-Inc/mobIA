"""Resolve expressao monetaria em lingua natural para centavos.

TEC-146. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo. Quem
decide a ordem de grandeza e este modulo, e nao o modelo -- ver D1 do desenho.
A gramatica e lista fixa e erra por falta; estende-la e decisao de card, nao
de quem passa por aqui.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Ruido que nao carrega valor. Sai antes de qualquer parsing para que
# "uns 500 mil" e "500 mil" sigam o mesmo caminho.
_RUIDO = re.compile(
    r"\b(r\$|reais?|uns?|umas?|cerca de|por volta de|mais ou menos|em torno de)\b"
)

# `\b` separa "mil" de "milhao": sem ele o primeiro padrao comeria o prefixo do
# segundo e "1 milhao" viraria mil.
_MULTIPLICADORES: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"\b(milhao|milhoes|milhões|milhão|mi)\b"), Decimal(1_000_000)),
    (re.compile(r"\b(mil|k)\b"), Decimal(1_000)),
)

_NUMERO = re.compile(r"\d[\d.]*(?:,\d+)?")


@dataclass(frozen=True)
class _Valor:
    """Um valor resolvido, e se a fala trazia marcador de grandeza.

    `tinha_marcador` nao e curiosidade: e o que separa "uns 500" (ambiguo) de
    "500 mil" (claro) na banda da Task 3. Um numero nu abaixo do piso quase
    certamente quis dizer outra coisa.
    """

    centavos: int
    tinha_marcador: bool
    # `compare=False` e o ponto: a Task 2 precisa do multiplicador aplicado
    # para distribuir o marcador numa faixa ("entre 400 e 500 mil" sao 400 MIL
    # e 500 mil). Sem `compare=False`, este campo entraria na igualdade do
    # dataclass e quebraria os asserts deste proprio arquivo de teste.
    fator: Decimal = field(default=Decimal(1), compare=False)


def _decimal_de(bruto: str) -> Decimal | None:
    """Ponto e separador de milhar; virgula e decimal. Convencao pt-BR."""
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None


def _valor_de(texto: str) -> _Valor | None:
    limpo = _RUIDO.sub(" ", texto.casefold())
    achado = _NUMERO.search(limpo)
    if achado is None:
        return None

    valor = _decimal_de(achado.group())
    if valor is None:
        return None

    # O marcador vale se aparecer DEPOIS do numero: "500 mil" multiplica,
    # "mil e quinhentos reais de condominio, imovel de 500" nao.
    resto = limpo[achado.end() :]
    tinha_marcador = False
    fator_aplicado = Decimal(1)
    for padrao, fator in _MULTIPLICADORES:
        if padrao.search(resto):
            valor *= fator
            tinha_marcador = True
            fator_aplicado = fator
            break

    centavos = (valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return _Valor(centavos=int(centavos), tinha_marcador=tinha_marcador,
                  fator=fator_aplicado)
