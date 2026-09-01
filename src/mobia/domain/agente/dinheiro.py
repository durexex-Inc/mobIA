"""Resolve expressao monetaria em lingua natural para centavos.

TEC-146. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo. Quem
decide a ordem de grandeza e este modulo, e nao o modelo -- ver D1 do desenho.
A gramatica e lista fixa e erra por falta; estende-la e decisao de card, nao
de quem passa por aqui.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum

from mobia.domain.agente.schemas import Intencao

# Ruido que nao carrega valor. Sai antes de qualquer parsing para que
# "uns 500 mil" e "500 mil" sigam o mesmo caminho.
# Nota: r$ precisa de trato diferente das palavras; sem \b consegue pegar
# "r$ " ou "r$", enquanto palavras inteiras ganham \b em torno.
_RUIDO = re.compile(
    r"r\$\s*|\b(?:reais?|uns?|umas?|cerca de|por volta de|mais ou menos|em torno de)\b"
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


# Preposicoes que abrem faixa. "de X a Y" e "entre X e Y" sao as duas formas
# que o corpus da TEC-145 traz; "X a Y" e a mesma coisa sem a abertura.
_FAIXA = re.compile(r"(?:entre\s+)?(.+?)\s+(?:a|e|ate)\s+(.+)", re.DOTALL)

_SO_MAXIMO = re.compile(r"\b(ate|no maximo|maximo|abaixo de|menos de)\b")
_SO_MINIMO = re.compile(r"\b(a partir de|no minimo|minimo|acima de|mais de)\b")


@dataclass(frozen=True)
class FaixaDePreco:
    """Faixa resolvida. Extremo nulo e faixa aberta daquele lado."""

    min_centavos: int | None = None
    max_centavos: int | None = None


def _faixa_de(expressao: str) -> FaixaDePreco | None:
    limpo = expressao.casefold()

    # Direcao antes de faixa: "ate 500 mil" casaria em `_FAIXA` pelo "ate",
    # com o lado esquerdo vazio. Testar a direcao primeiro evita o falso par.
    if _SO_MINIMO.search(limpo):
        valor = _valor_de(limpo)
        return None if valor is None else FaixaDePreco(min_centavos=valor.centavos)
    if _SO_MAXIMO.search(limpo):
        valor = _valor_de(limpo)
        return None if valor is None else FaixaDePreco(max_centavos=valor.centavos)

    par = _FAIXA.match(limpo)
    if par is not None:
        esquerda, direita = _valor_de(par.group(1)), _valor_de(par.group(2))
        if esquerda is not None and direita is not None:
            # O marcador do lado direito distribui para a esquerda quando o
            # esquerdo nao tem o seu: "entre 400 e 500 mil" sao 400 MIL e 500
            # mil, nao 400 reais e 500 mil. Quando a esquerda ja tem marcador
            # proprio ("800 mil a 1,2 milhao"), ela fica como esta -- usar o
            # fator ja aplicado por _valor_de evita reconstruir string para
            # descobrir o multiplicador de novo.
            minimo = esquerda.centavos
            if not esquerda.tinha_marcador and direita.tinha_marcador:
                minimo = int(esquerda.centavos * direita.fator)
            return FaixaDePreco(min_centavos=minimo, max_centavos=direita.centavos)

    valor = _valor_de(limpo)
    return None if valor is None else FaixaDePreco(max_centavos=valor.centavos)


# Bandas em centavos. Constantes de modulo, nao configuracao: a card pede
# configurabilidade para os PESOS DO SCORE (TEC-150), e nao diz nada sobre
# bandas de preco. Configuracao que ninguem pediu e superficie a mais.
_BANDA_DE_COMPRA = (3_000_000, 100_000_000_000)  # R$ 30 mil a R$ 1 bilhao
_BANDA_DE_ALUGUEL = (30_000, 20_000_000)  # R$ 300 a R$ 200 mil

_BANDAS = {
    Intencao.COMPRA: _BANDA_DE_COMPRA,
    Intencao.INVESTIMENTO: _BANDA_DE_COMPRA,
    Intencao.VENDER_IMOVEL: _BANDA_DE_COMPRA,
    Intencao.ALUGUEL: _BANDA_DE_ALUGUEL,
}

# Uniao das duas: na duvida, aceita. Fechar a banda para o lead ainda nao
# classificado custaria valores de aluguel legitimos, que sao a maioria dos
# valores baixos. Lacuna declarada no desenho.
_BANDA_FROUXA = (
    min(_BANDA_DE_COMPRA[0], _BANDA_DE_ALUGUEL[0]),
    max(_BANDA_DE_COMPRA[1], _BANDA_DE_ALUGUEL[1]),
)


class MotivoDaRecusa(StrEnum):
    """Tres motivos que mandam quem investiga para lados diferentes.

    AMBIGUA e IMPLAUSIVEL dizem que o LEAD foi impreciso; ILEGIVEL diz que o
    PARSER nao deu conta. Um pico de ILEGIVEL e trabalho para a proxima card
    da gramatica; um pico de AMBIGUA e sinal sobre como os leads deste
    produto falam de dinheiro.
    """

    AMBIGUA = "AMBIGUA"
    IMPLAUSIVEL = "IMPLAUSIVEL"
    ILEGIVEL = "ILEGIVEL"


@dataclass(frozen=True)
class Recusa:
    """Recusa com motivo -- nunca excecao. Ver `parsear`."""

    motivo: MotivoDaRecusa


def _tinha_marcador(expressao: str) -> bool:
    limpo = expressao.casefold()
    return any(padrao.search(limpo) for padrao, _ in _MULTIPLICADORES)


def parsear(expressao: str, intencao: Intencao) -> FaixaDePreco | Recusa:
    """Resolve a expressao, ou recusa com motivo. Nunca levanta.

    Chamador com `expressao` nula nao chega aqui: nao ha o que parsear, nada e
    gravado e nada e logado. E o turno comum, que nao fala de orcamento.
    """
    faixa = _faixa_de(expressao)
    if faixa is None:
        return Recusa(MotivoDaRecusa.ILEGIVEL)

    # Invertida antes da banda: os dois extremos podem estar dentro dela e
    # ainda assim a faixa nao fazer sentido.
    if (
        faixa.min_centavos is not None
        and faixa.max_centavos is not None
        and faixa.min_centavos > faixa.max_centavos
    ):
        return Recusa(MotivoDaRecusa.IMPLAUSIVEL)

    piso, teto = _BANDAS.get(intencao, _BANDA_FROUXA)
    extremos = [v for v in (faixa.min_centavos, faixa.max_centavos) if v is not None]

    for valor in extremos:
        if valor > teto:
            return Recusa(MotivoDaRecusa.IMPLAUSIVEL)
        if valor < piso:
            # Numero nu abaixo do piso e ambiguo, nao implausivel: o lead
            # quase certamente disse outra coisa. Com marcador explicito, ele
            # disse algo que nao fecha com a intencao.
            return Recusa(
                MotivoDaRecusa.AMBIGUA
                if not _tinha_marcador(expressao)
                else MotivoDaRecusa.IMPLAUSIVEL
            )

    return faixa
