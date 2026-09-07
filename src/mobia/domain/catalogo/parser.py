"""Le CSV ou JSON e devolve registro valido ou rejeicao, linha a linha.

TEC-156, RN-08.1 e RN-08.5. Puro: sem sessao, sem banco, sem ARQ, sem
Settings. E aqui que mora quase toda a densidade da card, e a pureza e o que
torna os casos testaveis sem subir Postgres -- a suite deste repo e lenta e os
testes de integracao flakeiam sob carga.

A unica excecao a essa lista e `models.Imovel`, importado para LER os limites
declarados das colunas de texto (ver `_limite_de_texto`). Continua sendo
declaracao, nao I/O: nenhuma linha daqui abre conexao, e os testes deste
parser seguem rodando sem Postgres.

**Os limites do schema sao checados AQUI, e nao no upsert.** Esta e a unica
camada que sabe o NUMERO DA LINHA. Um `uf` de "Sao Paulo" que atravesse o
parser entra num INSERT de 500 linhas, o Postgres derruba o lote com
StringDataRightTruncation, e o relatorio sai FALHOU sem linha e sem campo --
520 imoveis perdidos por um typo numa celula, no exato formato que a RN-08.5
recusa ("linha ruim nunca leva a FALHOU"). Por isso tamanho de texto, faixa de
inteiro, faixa de coordenada e limite de BIGINT sao rejeicao por linha.

**Estrito no conteudo, tolerante so na forma.** Coluna ausente, enum em
minuscula e inteiro que nao parseia sao rejeicao; nada e normalizado. O motivo
nao e purismo: normalizar entrada num arquivo e adivinhar, e adivinhar errado
grava um imovel com dado falso sem deixar rastro. A card pede o oposto --
um relatorio que diz o que falhou. Ver D5.

As duas tolerancias sao sobre CONSEGUIR LER a celula, nunca sobre o que ha
dentro dela: `utf-8-sig` (Excel exporta BOM) e delimitador `,` ou `;` (Excel
pt-BR exporta `;`). Sem a primeira, toda linha e rejeitada por "codigo
ausente"; sem a segunda, o arquivo inteiro vira uma coluna so. Nos dois casos
o sintoma nao aponta para a causa.

**`ArquivoInvalido` e a fronteira.** Ela e levantada pelo que o lote nao
absorve -- arquivo ilegivel, cabecalho sem coluna obrigatoria, JSON
malformado, extensao desconhecida. Nenhum desses e "uma linha", entao nenhum
cabe no relatorio por linha. Linha ruim NUNCA levanta.
"""

import csv
import io
import json
from collections.abc import Iterator
from decimal import Decimal, DecimalException

from mobia.domain.catalogo.enums import Operacao, StatusImovel, TipoImovel, Zona
from mobia.domain.catalogo.models import Imovel
from mobia.domain.catalogo.schemas import RegistroImovel, Rejeicao

# R$ 1.000 e R$ 500.000.000, em centavos. A faixa e larga o bastante para nao
# recusar imovel legitimo e estreita o bastante para o erro de unidade cair
# fora dela na grande maioria dos casos: quem digita centavos num campo de
# reais produz um numero mil vezes maior. Nao e guarda perfeita -- e a
# diferenca entre um erro que grita e um erro que nao deixa rastro. Ver D6.
PRECO_MINIMO_EM_CENTAVOS = 100_000
PRECO_MAXIMO_EM_CENTAVOS = 50_000_000_000

_OBRIGATORIAS = (
    "codigo",
    "titulo",
    "descricao",
    "tipo",
    "operacao",
    "bairro",
    "cidade",
    "uf",
    "area_util_m2",
    "quartos",
    "suites",
    "banheiros",
    "vagas",
    "status",
)

_SEPARADOR_DE_ARRAY = "|"

# Faixa do SMALLINT do Postgres, onde moram quartos, suites, banheiros e
# vagas. Um `99999` numa dessas celulas nao produz "muito quarto": produz um
# INSERT de 500 linhas que o Postgres derruba por overflow, e o relatorio sai
# com FALHOU, sem numero de linha e sem nome de campo -- por um typo numa
# celula. A RN-08.5 diz o oposto: linha ruim nunca leva a FALHOU.
#
# Escrita aqui, e nao derivada da coluna como os tamanhos de texto abaixo,
# porque `SmallInteger` nao publica limite nenhum para se ler. Quem trocar o
# tipo dessas colunas tem de trocar estas duas linhas junto.
FAIXA_DE_INTEIRO_PEQUENO = (-32_768, 32_767)

# Faixa do INTEGER, onde mora area_util_m2. Mesmo estrago, mesma razao.
FAIXA_DE_INTEIRO = (-2_147_483_648, 2_147_483_647)

# Faixa do BIGINT, onde moram os quatro campos de dinheiro em centavos. NAO e
# a guarda de plausibilidade de D6 -- esta e o limite fisico da coluna, e vale
# tambem para condominio e iptu_mensal, que por decisao de D6 nao tem guarda
# de faixa. As duas coisas sao diferentes: uma recusa valor implausivel, a
# outra recusa valor que a coluna nao guarda.
FAIXA_DE_INTEIRO_GRANDE = (-9_223_372_036_854_775_808, 9_223_372_036_854_775_807)

# Graus, e nao o limite da coluna. `Numeric(9, 6)` aceita no maximo tres
# digitos inteiros, entao uma latitude de "1234.5" estoura a coluna e leva o
# lote com ela; a faixa geografica e mais estreita que a coluna e pega o mesmo
# erro antes, com o numero da linha ainda na mao.
LATITUDE_MINIMA = Decimal(-90)
LATITUDE_MAXIMA = Decimal(90)
LONGITUDE_MINIMA = Decimal(-180)
LONGITUDE_MAXIMA = Decimal(180)


def _limite_de_texto(campo: str) -> int | None:
    """O `length` declarado da coluna, ou None quando ela nao tem teto (Text).

    Lido da DECLARACAO da coluna e nao copiado para uma constante daqui: um
    numero copiado se descola em silencio. Se `titulo` virasse `String(200)`,
    um `160` escrito neste arquivo passaria a recusar linha boa, e nenhum dos
    tres gates estaticos acusaria. `Imovel.__table__` e o schema declarado,
    nunca uma conexao -- o parser continua puro e testavel sem Postgres.
    """
    return getattr(Imovel.__table__.c[campo].type, "length", None)


class ArquivoInvalido(Exception):
    """O arquivo inteiro nao pode ser processado. Nao confundir com Rejeicao."""


def parsear(conteudo: bytes, *, nome_arquivo: str) -> Iterator[RegistroImovel | Rejeicao]:
    nome = nome_arquivo.lower()
    if nome.endswith(".csv"):
        yield from _parsear_csv(conteudo)
    elif nome.endswith(".json"):
        yield from _parsear_json(conteudo)
    else:
        raise ArquivoInvalido(f"extensao nao suportada em {nome_arquivo!r}; use .csv ou .json")


def _decodificar(conteudo: bytes) -> str:
    # utf-8-sig come o BOM quando ele existe e e identico a utf-8 quando nao.
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        raise ArquivoInvalido(f"arquivo nao e UTF-8 valido: {erro}") from erro


def _delimitador(cabecalho: str) -> str:
    # Escolha entre os dois unicos candidatos, pelo que aparece mais no
    # cabecalho. Nao usamos csv.Sniffer: ele adivinha entre muitos candidatos e
    # erra com campo que contem virgula.
    return ";" if cabecalho.count(";") > cabecalho.count(",") else ","


def _parsear_csv(conteudo: bytes) -> Iterator[RegistroImovel | Rejeicao]:
    texto = _decodificar(conteudo)
    primeira = texto.split("\n", 1)[0]
    leitor = csv.DictReader(io.StringIO(texto), delimiter=_delimitador(primeira))

    colunas = set(leitor.fieldnames or ())
    faltando = [c for c in _OBRIGATORIAS if c not in colunas]
    if faltando:
        raise ArquivoInvalido(f"cabecalho sem coluna obrigatoria: {', '.join(faltando)}")

    vistos: dict[str, int] = {}
    # `leitor.reader.line_num` conta LINHA FISICA do arquivo; `enumerate`
    # contaria REGISTRO. Uma `descricao` entre aspas com quebra de linha faz um
    # registro ocupar duas linhas, e dali para frente todo numero do relatorio
    # apontaria para a linha errada no editor de quem for corrigir -- e o
    # numero da linha e o produto desta card, nao um detalhe dela.
    #
    # O cabecalho e a linha 1, entao o primeiro registro ja deixa `line_num`
    # em 2. Para registro que ocupa varias linhas o numero e onde ele TERMINA:
    # o parser so sabe da extensao dele depois de ler a ultima. Para registro
    # de uma linha -- praticamente todo arquivo real -- as duas coincidem.
    for bruto in leitor:
        numero = leitor.reader.line_num
        yield _converter({k: (v or "") for k, v in bruto.items()}, numero, vistos)


def _parsear_json(conteudo: bytes) -> Iterator[RegistroImovel | Rejeicao]:
    texto = _decodificar(conteudo)
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise ArquivoInvalido(f"JSON malformado: {erro}") from erro

    if not isinstance(dados, list):
        raise ArquivoInvalido("JSON precisa ser uma lista de objetos, sem envelope")

    vistos: dict[str, int] = {}
    # Sem linha fisica correspondente: aqui "linha" e o indice 1-based do
    # elemento, e o relatorio declara qual convencao esta em uso.
    for indice, item in enumerate(dados, start=1):
        if not isinstance(item, dict):
            yield Rejeicao(linha=indice, motivo="elemento nao e um objeto")
            continue
        bruto = {k: str(v) if v is not None else "" for k, v in item.items()}
        yield _converter(bruto, indice, vistos)


def _converter(
    bruto: dict[str, str], linha: int, vistos: dict[str, int]
) -> RegistroImovel | Rejeicao:
    """Converte uma linha, acumulando TODOS os motivos antes de decidir.

    Acumular e nao devolver no primeiro erro: linha com tres campos ruins
    devolve um motivo com os tres, e o admin corrige tudo numa rodada. Ver D7.
    """
    motivos: list[str] = []

    def texto(campo: str, *, obrigatorio: bool = True) -> str:
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return valor
        limite = _limite_de_texto(campo)
        if limite is not None and len(valor) > limite:
            motivos.append(f"{campo} tem {len(valor)} caracteres; o maximo e {limite}")
        return valor

    def inteiro(campo: str, *, faixa: tuple[int, int], obrigatorio: bool = True) -> int | None:
        # `faixa` e obrigatoria na assinatura, e nao um default generoso: um
        # inteiro sem teto atravessa o parser e estoura a coluna no INSERT do
        # lote, e la nao ha mais numero de linha para relatar.
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return None
        try:
            numero = int(valor)
        except ValueError:
            motivos.append(f"{campo} nao e inteiro: {valor!r}")
            return None
        if not faixa[0] <= numero <= faixa[1]:
            motivos.append(
                f"{campo} fora da faixa: {valor!r} -- esperado entre {faixa[0]} e {faixa[1]}"
            )
            return None
        return numero

    def enumerado(campo: str, classe, *, obrigatorio: bool = True):
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return None
        try:
            return classe(valor)
        except ValueError:
            motivos.append(f"{campo} invalido: {valor!r}")
            return None

    def preco(campo: str, *, checar_faixa: bool = True) -> int | None:
        # `checar_faixa` existe porque condominio e iptu_mensal usam esta
        # mesma conversao reais->centavos mas NAO a guarda de plausibilidade:
        # a guarda existe para o erro de unidade em preco_venda/preco_aluguel
        # (RN-08.5, D6), e um condominio de R$ 850 e um IPTU de R$ 320 sao
        # valores legitimos, abaixo do piso pensado para preco de imovel.
        valor = bruto.get(campo, "").strip()
        if not valor:
            return None
        try:
            reais = Decimal(valor)
            # NaN e Infinity sao Decimal validos e o `numeric` do Postgres os
            # aceita; `is_finite` os recusa aqui, onde ainda ha numero de linha.
            if not reais.is_finite():
                raise ArithmeticError(valor)
            centavos = int((reais * 100).to_integral_value())
        except (DecimalException, ArithmeticError, ValueError):
            motivos.append(f"{campo} nao e um valor em reais: {valor!r}")
            return None
        # O limite da coluna vale para os quatro campos, com `checar_faixa` ou
        # sem: condominio e iptu_mensal nao tem guarda de plausibilidade (D6),
        # mas tambem nao cabem num BIGINT infinito. Sao coisas diferentes --
        # uma recusa valor implausivel, a outra recusa valor que a coluna nao
        # guarda. Sem esta, um condominio de "1e30" derruba o lote de 500.
        if not FAIXA_DE_INTEIRO_GRANDE[0] <= centavos <= FAIXA_DE_INTEIRO_GRANDE[1]:
            motivos.append(f"{campo} nao cabe na coluna: {valor!r}")
            return None
        if checar_faixa and not PRECO_MINIMO_EM_CENTAVOS <= centavos <= PRECO_MAXIMO_EM_CENTAVOS:
            motivos.append(
                f"{campo} implausivel: {valor!r} -- esperado entre "
                f"{PRECO_MINIMO_EM_CENTAVOS // 100} e "
                f"{PRECO_MAXIMO_EM_CENTAVOS // 100} reais"
            )
            return None
        return centavos

    def coordenada(campo: str, *, minimo: Decimal, maximo: Decimal) -> Decimal | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return None
        try:
            grau = Decimal(valor)
        except DecimalException:
            motivos.append(f"{campo} nao e uma coordenada: {valor!r}")
            return None
        # `is_finite` antes da comparacao, e por dois motivos independentes.
        # Um: comparar NaN com `<=` levantaria InvalidOperation aqui mesmo.
        # Dois, o que importa -- `Decimal("NaN")` e um Decimal valido e o
        # `numeric` do Postgres o aceita, e dali em diante `NaN != NaN` faz o
        # diff de `_mudou` acusar a linha como alterada em TODA reimportacao:
        # um UPDATE inutil que bumpa `updated_at` e faz a coluna mentir sobre
        # quando o imovel mudou pela ultima vez.
        if not grau.is_finite():
            motivos.append(f"{campo} nao e uma coordenada: {valor!r}")
            return None
        if not minimo <= grau <= maximo:
            motivos.append(
                f"{campo} fora da faixa: {valor!r} -- esperado entre {minimo} e {maximo}"
            )
            return None
        return grau

    def lista(campo: str) -> tuple[str, ...]:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return ()
        return tuple(p.strip() for p in valor.split(_SEPARADOR_DE_ARRAY) if p.strip())

    codigo = texto("codigo")
    if codigo and codigo in vistos:
        motivos.append(
            f"codigo {codigo!r} repetido no arquivo (ja apareceu na linha {vistos[codigo]})"
        )

    titulo = texto("titulo")
    descricao = texto("descricao")
    tipo = enumerado("tipo", TipoImovel)
    operacao = enumerado("operacao", Operacao)
    preco_venda = preco("preco_venda")
    preco_aluguel = preco("preco_aluguel")
    condominio = preco("condominio", checar_faixa=False)
    iptu_mensal = preco("iptu_mensal", checar_faixa=False)
    bairro = texto("bairro")
    cidade = texto("cidade")
    uf = texto("uf")
    zona = enumerado("zona", Zona, obrigatorio=False)
    latitude = coordenada("latitude", minimo=LATITUDE_MINIMA, maximo=LATITUDE_MAXIMA)
    longitude = coordenada("longitude", minimo=LONGITUDE_MINIMA, maximo=LONGITUDE_MAXIMA)
    area = inteiro("area_util_m2", faixa=FAIXA_DE_INTEIRO)
    quartos = inteiro("quartos", faixa=FAIXA_DE_INTEIRO_PEQUENO)
    suites = inteiro("suites", faixa=FAIXA_DE_INTEIRO_PEQUENO)
    banheiros = inteiro("banheiros", faixa=FAIXA_DE_INTEIRO_PEQUENO)
    vagas = inteiro("vagas", faixa=FAIXA_DE_INTEIRO_PEQUENO)
    status = enumerado("status", StatusImovel)

    # Espelha o CHECK da tabela. So checa quando nenhum dos dois campos ja
    # gerou motivo proprio -- senao "preco implausivel" viria acompanhado de
    # "ao menos um preco" e o segundo confundiria em vez de informar.
    if (
        preco_venda is None
        and preco_aluguel is None
        and not any(m.startswith(("preco_venda", "preco_aluguel")) for m in motivos)
    ):
        motivos.append("ao menos um preco e obrigatorio (preco_venda ou preco_aluguel)")

    if motivos:
        return Rejeicao(linha=linha, motivo="; ".join(motivos))

    # Registrado so depois de a linha passar: uma linha rejeitada nao "reserva"
    # o codigo, senao a linha boa seguinte com o mesmo codigo seria recusada
    # por causa de uma linha que nem entrou.
    vistos[codigo] = linha

    assert tipo is not None and operacao is not None and status is not None
    assert area is not None and quartos is not None and suites is not None
    assert banheiros is not None and vagas is not None
    return RegistroImovel(
        linha=linha,
        codigo=codigo,
        titulo=titulo,
        descricao=descricao,
        tipo=tipo,
        operacao=operacao,
        preco_venda=preco_venda,
        preco_aluguel=preco_aluguel,
        condominio=condominio,
        iptu_mensal=iptu_mensal,
        bairro=bairro,
        cidade=cidade,
        uf=uf,
        zona=zona,
        latitude=latitude,
        longitude=longitude,
        area_util_m2=area,
        quartos=quartos,
        suites=suites,
        banheiros=banheiros,
        vagas=vagas,
        caracteristicas=lista("caracteristicas"),
        fotos=lista("fotos"),
        status=status,
    )
