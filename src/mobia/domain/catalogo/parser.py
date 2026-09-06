"""Le CSV ou JSON e devolve registro valido ou rejeicao, linha a linha.

TEC-156, RN-08.1 e RN-08.5. Puro: sem sessao, sem banco, sem ARQ, sem
Settings. E aqui que mora quase toda a densidade da card, e a pureza e o que
torna os casos testaveis sem subir Postgres -- a suite deste repo e lenta e os
testes de integracao flakeiam sob carga.

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
    # O cabecalho e a linha 1, entao o primeiro registro e a linha 2. O numero
    # tem que bater com o que o editor mostra para quem for corrigir.
    for numero, bruto in enumerate(leitor, start=2):
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
        if obrigatorio and not valor:
            motivos.append(f"{campo} ausente")
        return valor

    def inteiro(campo: str, *, obrigatorio: bool = True) -> int | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            if obrigatorio:
                motivos.append(f"{campo} ausente")
            return None
        try:
            return int(valor)
        except ValueError:
            motivos.append(f"{campo} nao e inteiro: {valor!r}")
            return None

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
            centavos = int((Decimal(valor) * 100).to_integral_value())
        except (DecimalException, ArithmeticError, ValueError):
            motivos.append(f"{campo} nao e um valor em reais: {valor!r}")
            return None
        if checar_faixa and not PRECO_MINIMO_EM_CENTAVOS <= centavos <= PRECO_MAXIMO_EM_CENTAVOS:
            motivos.append(
                f"{campo} implausivel: {valor!r} -- esperado entre "
                f"{PRECO_MINIMO_EM_CENTAVOS // 100} e "
                f"{PRECO_MAXIMO_EM_CENTAVOS // 100} reais"
            )
            return None
        return centavos

    def coordenada(campo: str) -> Decimal | None:
        valor = bruto.get(campo, "").strip()
        if not valor:
            return None
        try:
            return Decimal(valor)
        except DecimalException:
            motivos.append(f"{campo} nao e uma coordenada: {valor!r}")
            return None

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
    latitude = coordenada("latitude")
    longitude = coordenada("longitude")
    area = inteiro("area_util_m2")
    quartos = inteiro("quartos")
    suites = inteiro("suites")
    banheiros = inteiro("banheiros")
    vagas = inteiro("vagas")
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
