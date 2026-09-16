"""Resolve expressao monetaria em lingua natural para centavos.

TEC-146. Puro de proposito: sem I/O, sem banco, sem chamada ao modelo. Quem
decide a ordem de grandeza e este modulo, e nao o modelo -- ver D1 do desenho.
A gramatica e lista fixa e erra por falta; estende-la e decisao de card, nao
de quem passa por aqui.

**Nem `parsear` nem `_faixa_de` levantam.** A expressao chega de uma chamada ao
modelo, que por sua vez repete a fala do lead: qualquer sequencia de caracteres
e entrada valida deste modulo, inclusive uma linha digitavel de boleto colada
no meio da conversa. Uma excecao aqui vira `RespostaInvalida` no classificador,
o turno inteiro vai a `FAILED` e **o lead nao recebe resposta nenhuma** por
causa de um campo de enriquecimento. Toda aritmetica deste arquivo esta sob
guarda por causa disso, e `_BEM_FORMADO` limita o tamanho do numero antes de a
aritmetica comecar.
"""

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, DecimalException
from enum import StrEnum

from mobia.domain.agente.schemas import Intencao

# Ruido que nao carrega valor. Sai antes de qualquer parsing para que
# "uns 500 mil" e "500 mil" sigam o mesmo caminho.
# Nota: r$ precisa de trato diferente das palavras; sem \b consegue pegar
# "r$ " ou "r$", enquanto palavras inteiras ganham \b em torno.
_RUIDO = re.compile(
    r"r\$\s*|\b(?:reais?|uns?|umas?|cerca de|por volta de|mais ou menos|em torno de)\b"
)

# `r$` sobrevive so aqui: `_RUIDO` o apaga antes do parsing (ele nao muda o
# numero), mas a D3 do desenho conta o cifrao entre os marcadores que separam
# `AMBIGUA` de `IMPLAUSIVEL` -- quem escreve "R$ 500" nao esqueceu a ordem de
# grandeza, disse um valor que nao fecha. Ver `_tinha_marcador`.
_MARCADOR_DE_MOEDA = re.compile(r"r\$")

# `\b` separa "mil" de "milhao": sem ele o primeiro padrao comeria o prefixo do
# segundo e "1 milhao" viraria mil.
#
# `bilhao` entrou na revisao final por um motivo estrutural, e nao por
# antecipacao: o TETO da banda da D3 e R$ 1 bilhao, entao sem esta linha a
# gramatica nao conseguia dizer o proprio limite superior dela -- "2 bilhoes"
# resolvia para R$ 2,00, um erro de 10^9 que so nao era gravado porque dois
# reais tambem caem fora da banda, e que era logado como `AMBIGUA` (culpa do
# lead) em vez de `IMPLAUSIVEL`. A abreviacao "bi" NAO entra: "mi" ja existia e
# tem uso corrente numa fala de imovel, "bi" nao, e cada alternativa a mais e
# superficie de falso positivo.
_MULTIPLICADORES: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"\b(bilhao|bilhoes|bilhões|bilhão)\b"), Decimal(1_000_000_000)),
    (re.compile(r"\b(milhao|milhoes|milhões|milhão|mi)\b"), Decimal(1_000_000)),
    (re.compile(r"\b(mil|k)\b"), Decimal(1_000)),
)

# Casa o token numerico INTEIRO -- digitos com pontos e virgulas dentro -- e
# nao so o prefixo bem formado dele. A diferenca decide dois casos:
#
#   "1.5 milhao"  o token e "1.5", que nao e forma pt-BR nenhuma. Um padrao que
#                 casasse so o prefixo leria "1" e devolveria R$ 1 milhao em
#                 silencio; casando o token todo, `_BEM_FORMADO` reprova e a
#                 expressao vira ILEGIVEL.
#   boleto        47 digitos casam num token so, `_BEM_FORMADO` reprova, e a
#                 aritmetica nunca roda. Sem o limite, `quantize` estourava a
#                 precisao de 28 digitos do contexto decimal e levantava
#                 `InvalidOperation` -- ver o docstring do modulo.
_NUMERO = re.compile(r"\d[\d.,]*")

# A forma que o parser aceita: milhar em grupos de tres separados por ponto, ou
# inteiro corrido de ate 12 digitos, com no maximo duas casas decimais depois
# da virgula. Doze digitos sao R$ 999 bilhoes -- tres ordens de grandeza acima
# do teto da banda, entao nada gravavel e recusado aqui, e a aritmetica fica
# duas dezenas de digitos abaixo do limite do contexto decimal.
_BEM_FORMADO = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d{1,12}(?:,\d{1,2})?")


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
    """Ponto e separador de milhar; virgula e decimal. Convencao pt-BR.

    So aceita o que `_BEM_FORMADO` aprova. A checagem fica aqui, e nao so no
    chamador, porque e ela que garante que a aritmetica de `_resolver` nunca
    receba um numero grande o bastante para estourar o contexto decimal.
    """
    if not _BEM_FORMADO.fullmatch(bruto):
        return None
    try:
        return Decimal(bruto.replace(".", "").replace(",", "."))
    except DecimalException:
        return None


def _negativo(texto: str, inicio: int) -> bool:
    """O sinal fica fora de `_NUMERO`, e "-500 mil" nao e orcamento.

    Sem esta checagem o sinal era simplesmente descartado e a expressao virava
    R$ 500.000 -- valor dentro da banda, gravado em silencio. O hifen tambem
    NAO abre faixa ("300-450 mil"): a gramatica da D3 lista `entre X e Y`,
    `de X a Y` e `X a Y`, e nada mais. As duas leituras do hifen chegam ao
    mesmo lugar (recusa), e a recusa e logada como ILEGIVEL, que e a metrica
    do buraco da gramatica.
    """
    return texto[:inicio].rstrip().endswith("-")


def _resolver(bruto: str, sufixo: str) -> _Valor | None:
    """Um numero, e o trecho sobre o qual o marcador dele manda.

    `sufixo` e o escopo do marcador de grandeza, e quem o delimita e o
    chamador -- e essa delimitacao que impede o "mil" de um lado da faixa
    multiplicar o numero do outro lado.
    """
    valor = _decimal_de(bruto)
    if valor is None:
        return None

    # O marcador vale se aparecer DEPOIS do numero: "500 mil" multiplica,
    # "mil e quinhentos reais de condominio, imovel de 500" nao.
    tinha_marcador = False
    fator_aplicado = Decimal(1)
    for padrao, fator in _MULTIPLICADORES:
        if padrao.search(sufixo):
            valor *= fator
            tinha_marcador = True
            fator_aplicado = fator
            break

    try:
        centavos = (valor * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except DecimalException:
        # Inalcancavel com `_BEM_FORMADO` na frente. Fica porque o contrato
        # "nunca levanta" nao pode depender de um regex noutra funcao.
        return None
    return _Valor(centavos=int(centavos), tinha_marcador=tinha_marcador, fator=fator_aplicado)


def _valor_de(texto: str) -> _Valor | None:
    """O PRIMEIRO numero do texto, com todo o resto como escopo do marcador."""
    limpo = _RUIDO.sub(" ", texto.casefold())
    achado = _NUMERO.search(limpo)
    if achado is None or _negativo(limpo, achado.start()):
        return None
    return _resolver(achado.group().rstrip(".,"), limpo[achado.end() :])


# `reais` DEPOIS do numero e marcador de moeda tanto quanto `R$` antes dele.
# Precisa de padrao proprio porque `_RUIDO` apaga a palavra antes de qualquer
# parsing -- para `parsear` ela e ruido mesmo, mas para `valores_em` ela e
# metade da evidencia de que aquele numero e dinheiro.
_MARCADOR_DE_REAIS = re.compile(r"\A\s*reais?\b")

# Quantos caracteres antes do numero ainda contam como lugar do `R$`. Tres
# bastam para "r$ " e nao alcancam o numero anterior.
_ALCANCE_DO_CIFRAO = 3


def valores_em(texto: str) -> tuple[int, ...]:
    """Todos os valores monetarios do texto, em centavos, na ordem.

    Diferente de `parsear`, que resolve UMA expressao ja isolada pelo modelo,
    este varre prosa livre. A diferenca de contrato que importa: aqui um
    numero so conta se vier com marcador -- `R$` antes, `reais` depois, ou
    sufixo de grandeza. Sem isso "2 quartos" e "80 m2" viram dinheiro, e a
    guarda da TEC-161 passa a bloquear turno correto (D2 do desenho).

    **Erra por falta, de proposito.** "esse ai sai por 750" nao e detectado.
    E a mesma politica que o docstring deste modulo ja declara para a
    gramatica inteira, e a alternativa -- aceitar numero nu -- troca um falso
    negativo por uma enxurrada de falso positivo.

    Nao levanta, pelo mesmo motivo que `parsear` nao levanta.
    """
    limpo = texto.casefold()
    achados = list(_NUMERO.finditer(limpo))
    valores: list[int] = []
    for indice, achado in enumerate(achados):
        if _negativo(limpo, achado.start()):
            continue
        # O escopo do marcador termina no proximo numero. E a mesma delimitacao
        # que `_faixa_de` faz para impedir o "mil" de um lado da faixa de
        # multiplicar o numero do outro lado -- ver o docstring de `_resolver`.
        fim = achados[indice + 1].start() if indice + 1 < len(achados) else len(limpo)
        sufixo = limpo[achado.end() : fim]
        antes = limpo[max(0, achado.start() - _ALCANCE_DO_CIFRAO) : achado.start()]

        valor = _resolver(achado.group().rstrip(".,"), sufixo)
        if valor is None:
            continue
        tem_marcador = (
            valor.tinha_marcador
            or _MARCADOR_DE_MOEDA.search(antes) is not None
            or _MARCADOR_DE_REAIS.match(sufixo) is not None
        )
        if tem_marcador:
            valores.append(valor.centavos)
    return tuple(valores)


# Conectores de faixa: as tres formas da D3 (`entre X e Y`, `de X a Y`,
# `X a Y`) reduzem-se todas a "a", "e" ou "ate" ENTRE os dois numeros. Virgula
# e espaco em volta sao ruido de escrita.
_CONECTOR_DE_FAIXA = re.compile(r"[\s,]*(?:ate|até|a|e)[\s,]*")

# Acentuados junto com a forma sem acento, pela mesma razao que
# `_MULTIPLICADORES`: quem digita e o lead, e "no minimo"/"no mínimo" sao a
# mesma frase. Sem os acentos, "no mínimo 300 mil" nao casava aqui e caia no
# fallback -- que e MAXIMO -- invertendo o filtro de busca em silencio. As
# formas de maximo escapavam do sintoma so porque o fallback ja e maximo.
_SO_MAXIMO = re.compile(r"\b(at[eé]|no m[aá]ximo|m[aá]ximo|abaixo de|menos de)\b")
_SO_MINIMO = re.compile(r"\b(a partir de|no m[ií]nimo|m[ií]nimo|acima de|mais de)\b")


@dataclass(frozen=True)
class FaixaDePreco:
    """Faixa resolvida. Extremo nulo e faixa aberta daquele lado."""

    min_centavos: int | None = None
    max_centavos: int | None = None


def _sem_marcador(trecho: str) -> str:
    """Tira os marcadores de grandeza do trecho.

    Usada so no separador de faixa: o "mil" de "de 300 mil ate 500 mil"
    pertence ao numero da ESQUERDA, e nao ao conector. Sem esta limpeza o
    separador " mil ate " nao pareceria conector, a faixa seria recusada, e
    "de X ate Y" -- portugues corrente -- nao teria como ser lido.
    """
    for padrao, _ in _MULTIPLICADORES:
        trecho = padrao.sub(" ", trecho)
    return trecho


def _faixa_de(expressao: str) -> FaixaDePreco | None:
    """Resolve direcao e faixa amarrando cada numero a clausula dele.

    A decisao estrutural, e a que fechou tres defeitos de uma vez na revisao
    final: **quem decide a forma e a quantidade de numeros**, e nao uma
    sequencia de regexes sobre a string inteira.

    A versao anterior testava direcao sobre a expressao toda ANTES de testar
    faixa, e resolvia o valor sobre a expressao toda depois. Isso fazia
    "de 300 mil ate 500 mil" virar um maximo de R$ 300.000 -- o `ate` casava a
    direcao, e o primeiro numero da string respondia por ela. Quarenta por
    cento abaixo do que o lead disse, dentro da banda, gravado sem log. Pelo
    mesmo caminho "apartamento de 120m2 ate 600 mil" virava R$ 120.000, e a
    unica linha do corpus que afirma piso ("minha faixa e de 300 a 450 mil,
    abaixo disso nao acho nada decente") perdia o minimo, porque o regex de
    faixa partia no primeiro "e" da frase e desistia.

    Agora:

    - **Um numero** -- a direcao vale, procurada na expressao inteira: nao ha
      clausula concorrente, e "500 mil no maximo" e tao corrente quanto
      "no maximo 500 mil". Sem direcao, valor nu e maximo (D3).
    - **Dois numeros separados apenas por conector** -- e faixa, e a faixa
      vence a direcao: quem diz "a partir de 300 mil a 500 mil" enunciou os
      dois extremos, e ficar so com o piso perde metade do que foi dito. Cada
      lado resolve o marcador dentro do proprio escopo.
    - **Qualquer outra coisa** -- recusa (ILEGIVEL). Dois numeros que nao sao
      faixa ("2 quartos ate 600 mil") ou tres numeros nao dizem ao parser qual
      deles e dinheiro, e chutar custa um filtro de busca errado que ninguem
      atribui ao parser. E a mesma assimetria da D6: recusar custa uma
      repergunta.
    """
    limpo = _RUIDO.sub(" ", expressao.casefold())
    achados = list(_NUMERO.finditer(limpo))

    if len(achados) == 1:
        # `_valor_de` de novo sobre o texto ja limpo: com um numero so ele
        # acha o mesmo e o escopo do marcador e todo o resto, que e
        # exatamente a regra deste ramo. `_RUIDO.sub` sobre texto ja limpo e
        # no-op, entao repetir a limpeza nao muda nada.
        valor = _valor_de(limpo)
        if valor is None:
            return None
        if _SO_MINIMO.search(limpo):
            return FaixaDePreco(min_centavos=valor.centavos)
        return FaixaDePreco(max_centavos=valor.centavos)

    if len(achados) != 2:
        return None

    primeiro, segundo = achados
    if _negativo(limpo, primeiro.start()) or _negativo(limpo, segundo.start()):
        return None

    separador = limpo[primeiro.end() : segundo.start()]
    if not _CONECTOR_DE_FAIXA.fullmatch(_sem_marcador(separador)):
        return None

    # O escopo do marcador da esquerda e o separador, e nao o resto da string:
    # e o que amarra o "mil" de "de 300 mil ate 500 mil" ao 300.
    esquerda = _resolver(primeiro.group().rstrip(".,"), separador)
    direita = _resolver(segundo.group().rstrip(".,"), limpo[segundo.end() :])
    if esquerda is None or direita is None:
        return None

    # O marcador do lado direito distribui para a esquerda quando o esquerdo
    # nao tem o seu: "entre 400 e 500 mil" sao 400 MIL e 500 mil, nao 400
    # reais e 500 mil. Quando a esquerda ja tem marcador proprio ("800 mil a
    # 1,2 milhao"), ela fica como esta -- usar o fator ja aplicado por
    # `_resolver` evita reconstruir string para descobrir o multiplicador.
    minimo = esquerda.centavos
    if not esquerda.tinha_marcador and direita.tinha_marcador:
        minimo = int(esquerda.centavos * direita.fator)
    return FaixaDePreco(min_centavos=minimo, max_centavos=direita.centavos)


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
# valores baixos. Lacuna declarada no desenho -- e estreitada, para o numero
# NU, pelo `piso_do_numero_nu` de `parsear`.
#
# `_BANDAS.get` cai aqui para TODA intencao que nao esta na tabela acima, e
# isso inclui as duas nao-monetarias: SUPORTE_CONTRATO e FORA_DE_ESCOPO, nao
# so INDEFINIDA. Nao e acidente do `.get`: um numero solto numa conversa de
# suporte ao contrato nao e orcamento de compra nem de aluguel, mas recusar
# de cara e decisao de escopo que pertence a outra card -- a banda frouxa pelo
# menos barra um valor absurdo (ex.: "500 milhoes" numa duvida de contrato)
# sem o modulo precisar saber julgar a intencao. Rio abaixo os dois membros
# divergem: `campos_a_gravar` (repositorio.py) descarta tudo para
# FORA_DE_ESCOPO, entao um preco parseado ali nunca chega ao banco; para
# SUPORTE_CONTRATO nao ha essa guarda, e o preco e gravado como qualquer
# outro. Se isso for um problema, o conserto e no filtro de gravacao, nao
# aqui: este modulo so decide se o numero e plausivel, nao se a intencao
# devia gravar preco.
_BANDA_FROUXA = (
    min(_BANDA_DE_COMPRA[0], _BANDA_DE_ALUGUEL[0]),
    max(_BANDA_DE_COMPRA[1], _BANDA_DE_ALUGUEL[1]),
)


def mudou_de_banda(antiga: Intencao | None, nova: Intencao) -> bool:
    """A intencao nova admite valores de outra faixa que a antiga? TEC-136.

    Existe aqui, e nao em `context/`, porque a resposta e uma consequencia de
    `_BANDAS` -- a mesma tabela que `parsear` usa para recusar numero
    implausivel. Duas copias dessa tabela divergiriam em silencio, e a
    divergencia so apareceria como orcamento sobrevivendo a uma troca que
    deveria te-lo apagado.

    `antiga is None` e "a conversa ainda nao tinha intencao acumulada quando o
    numero foi dito", e devolve True de proposito: o valor entrou sob
    `_BANDA_FROUXA`, que e a uniao das duas e portanto nao validou nada. E a
    porta que o comentario de `piso_do_numero_nu` descreve.

    Intencao fora de `_BANDAS` devolve False -- a banda frouxa nao restringe,
    entao nao ha o que invalidar. Vale para SUPORTE_CONTRATO, que e gravavel,
    e nao chega a valer para INDEFINIDA, que `campos_a_gravar` nunca grava.
    """
    if nova not in _BANDAS:
        return False
    if antiga is None:
        return True
    return _BANDAS.get(antiga) is not _BANDAS[nova]


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
    """Se a fala trouxe ordem de grandeza explicita -- cifrao incluido.

    A D3 lista `mil`, `k`, `milhao` **e `R$`** como os marcadores que separam
    `AMBIGUA` de `IMPLAUSIVEL`, e o cifrao estava faltando aqui. Nao e detalhe
    de log: as duas recusas apontam para lados opostos. Quem escreve "uns 500"
    para uma compra provavelmente quis dizer outro numero (AMBIGUA); quem
    escreve "R$ 500" pos a moeda de proposito e disse um valor que nao fecha
    com a intencao (IMPLAUSIVEL). Recebe a expressao CRUA, antes de `_RUIDO`
    apagar o cifrao.
    """
    limpo = expressao.casefold()
    return bool(_MARCADOR_DE_MOEDA.search(limpo)) or any(
        padrao.search(limpo) for padrao, _ in _MULTIPLICADORES
    )


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
    tinha_marcador = _tinha_marcador(expressao)

    # O numero NU responde ao piso de COMPRA quando a banda e a frouxa, e este
    # e o unico ponto em que a banda frouxa deixa de ser a uniao pura.
    #
    # O motivo e que a banda frouxa nao e uma banda de verdade: e a ausencia de
    # uma. Sem esta linha, "uns 500" com intencao INDEFINIDA -- o momento comum
    # da PRIMEIRA mencao de orcamento -- era aceito como R$ 500, que e
    # exatamente o defeito que abre o desenho desta card. `campos_a_gravar`
    # continua nunca apagando por si so, e turno nenhum revalida o que ja esta
    # gravado -- mas desde a TEC-136 quem fecha esta porta e
    # `aplicar_mudanca_de_intencao` (RN-03.3, repositorio.py): no turno em que
    # `mudou_de_banda` acha a troca, ela descarta a faixa gravada antes que o
    # valor admitido sob INDEFINIDA sobreviva para virar o filtro de uma busca
    # ja classificada COMPRA.
    #
    # Vale para as tres intencoes sem banda propria, e nao so para INDEFINIDA:
    # a regra e da banda frouxa, e o modulo nao tem por que saber qual dos
    # membros dela esta em jogo -- e a mesma razao pela qual `_BANDAS` e
    # tabela parcial com fallback em vez de mapa total do enum.
    #
    # Custa uma repergunta ao lead de aluguel que escreve "1500" nu antes de a
    # intencao estar decidida; com marcador ("1,5 mil", "R$ 1.500") ele passa
    # na hora. E o mesmo balanco da D6: recusar custa uma pergunta, aceitar
    # errado custa um filtro de busca que ninguem atribui ao parser.
    piso_do_numero_nu = piso if intencao in _BANDAS else _BANDA_DE_COMPRA[0]
    extremos = [v for v in (faixa.min_centavos, faixa.max_centavos) if v is not None]

    for valor in extremos:
        if valor > teto:
            return Recusa(MotivoDaRecusa.IMPLAUSIVEL)
        if valor < piso:
            # Numero nu abaixo do piso e ambiguo, nao implausivel: o lead
            # quase certamente disse outra coisa. Com marcador explicito, ele
            # disse algo que nao fecha com a intencao.
            return Recusa(
                MotivoDaRecusa.AMBIGUA if not tinha_marcador else MotivoDaRecusa.IMPLAUSIVEL
            )
        if not tinha_marcador and valor < piso_do_numero_nu:
            return Recusa(MotivoDaRecusa.AMBIGUA)

    return faixa


def ticket_de(expressao: str) -> int | None:
    """O ticket do investidor, em centavos. TEC-153, RN-05.2.

    **Reusa `parsear` e colapsa na borda**, em vez de um segundo parser
    monetario: a TEC-146 gastou uma card inteira consertando uma segunda
    fonte para a mesma verdade, e a normalizacao de "uns 800 mil" nao muda
    porque o campo mudou de nome.

    O colapso e necessario porque a SEMANTICA difere. Numa busca, "ate 800
    mil" e um teto e a faixa tem dois extremos. Num ticket, e o montante
    disponivel: um valor so. Toma-se `max_centavos`, e `min_centavos` quando
    so ele veio -- "a partir de 800 mil" como ticket ainda descreve 800 mil
    de dinheiro na mao.

    `Recusa` devolve `None` sem levantar: recusa de valor e caminho normal
    desde a TEC-148.
    """
    resultado = parsear(expressao, Intencao.INVESTIMENTO)
    if not isinstance(resultado, FaixaDePreco):
        return None
    return resultado.max_centavos if resultado.max_centavos is not None else resultado.min_centavos
