"""Asserta de ausencia sobre log tem de poder reprovar. TEC-289.

O `configure_logging` do app usa `structlog.processors.JSONRenderer()`, que
serializa no padrao `ensure_ascii=True`. Todo caractere fora do ASCII vira
`\\uXXXX` na mensagem renderizada -- e `caplog.text` e a mensagem renderizada.
Logo, `assert "não falo de imóveis" not in caplog.text` passa **com o texto
dentro do log**: a agulha tem acento, o palheiro foi escapado, e os dois nunca
se encontram.

Isso importa neste repo em particular por causa da TEC-267: todo texto que o
lead recebe e acentuado. A familia de asserta que mais precisa funcionar nos
testes de log -- "o texto que mandamos ao lead nao vazou para o log" -- e
exatamente a que nasce vazia.

**Nenhuma asserta do repo esta vazia hoje**, e foi medido: as 70 assertas de
ausencia sobre log tem agulha ASCII, e a unica acentuada
(`TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO`, em `test_conversa_encerrada.py`) ja
esta protegida com `ensure_ascii=False` desde a TEC-138. Este arquivo e
preventivo: ele existe para o dia em que alguem acentuar uma fixture de fala
do lead -- que e o que a TEC-267 pede -- e a asserta de PII ao lado silenciar
sem ficar vermelha.

**O `ruff` nao resolve.** Nenhuma das 970 regras trata de `ensure_ascii`; as
que tem "ascii" no nome sao sobre identificador (`PLC2401`, `PLC2403`) e
caractere ambiguo (`RUF001-003`). Por isso a guarda e um teste com `ast`, no
molde do que `scripts/comentarios_tocados.py` ja faz.
"""

import ast
import importlib
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import structlog
from conftest import log_legivel  # type: ignore[import-not-found]

from mobia.app.logging import configure_logging

RAIZ_DOS_TESTES = Path(__file__).resolve().parent.parent

# Agulha acentuada usada pelos testes do mecanismo. Ela imita o que o produto
# de fato diz -- e o encerramento fora de escopo da TEC-138 -- porque o valor
# desta guarda depende de o caso exemplar ser realista.
AGULHA_ACENTUADA = "Acho que não falo de imóveis"

# A unica saida da guarda, e ela existe por um caso so: o teste que PROVA a
# armadilha precisa escrever uma asserta vazia de proposito. Marca na propria
# linha, e nao exclusao do arquivo inteiro -- uma asserta vazia escrita aqui
# por descuido continua sendo pega. `test_a_marca_nao_escapou_deste_arquivo`
# impede que ela vire porta dos fundos em outro lugar.
MARCA_DE_VACUIDADE_PROPOSITAL = "# TEC-289: vazia de proposito"


class Achado(NamedTuple):
    """Uma asserta de ausencia que nao pode reprovar."""

    caminho: str
    linha: int
    agulha: str


class NaoResolvida(NamedTuple):
    """Uma agulha que a guarda nao conseguiu reduzir a um valor.

    Nao reprova nada -- ver a docstring de `_achados_em`.
    """

    caminho: str
    linha: int
    expressao: str


def _palheiro_escapado(no: ast.expr, dumps_sem_flag: dict[str, bool]) -> bool:
    """O palheiro e log renderizado, com `\\uXXXX` no lugar do acento?

    Tres formas, e a terceira e a que exige o mapa. `caplog.text` e
    `registro.getMessage()` sao sempre escapados. `json.dumps(...)` depende do
    `ensure_ascii`, e ele tanto pode estar na propria expressao quanto numa
    variavel atribuida antes (`corpo_serializado = json.dumps(corpo, ...)`),
    que e a forma que `test_conversa_encerrada.py` usa.
    """
    if isinstance(no, ast.Attribute) and no.attr == "text":
        return True
    if isinstance(no, ast.Call):
        if isinstance(no.func, ast.Attribute) and no.func.attr == "getMessage":
            return True
        if isinstance(no.func, ast.Attribute) and no.func.attr == "dumps":
            return not _tem_flag(no)
        # `caplog.text.casefold()` e afins: o escape esta no alvo, nao na chamada.
        return _palheiro_escapado(no.func, dumps_sem_flag)
    if isinstance(no, ast.Attribute):
        return _palheiro_escapado(no.value, dumps_sem_flag)
    if isinstance(no, ast.Name):
        return dumps_sem_flag.get(no.id, False)
    return False


def _tem_flag(chamada: ast.Call) -> bool:
    """A chamada passa `ensure_ascii=False` explicitamente?

    `is False` e nao falsidade: `ensure_ascii=0` seria a mesma coisa para o
    `json`, mas ninguem escreve isso, e aceitar qualquer falsy abriria a porta
    para um `ensure_ascii=variavel` que a guarda nao sabe avaliar.
    """
    return any(
        palavra.arg == "ensure_ascii"
        and isinstance(palavra.value, ast.Constant)
        and palavra.value.value is False
        for palavra in chamada.keywords
    )


def _dumps_por_variavel(arvore: ast.AST) -> dict[str, bool]:
    """Nome -> "foi atribuido de um `json.dumps` SEM `ensure_ascii=False`".

    Um mapa por arquivo, e nao por funcao, de proposito: errar para o lado de
    considerar escapado nao cria achado falso sozinho -- so cria se a agulha
    daquela asserta tambem for acentuada, que e o caso que se quer pegar.
    """
    mapa: dict[str, bool] = {}
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Assign) or not isinstance(no.value, ast.Call):
            continue
        chamada = no.value
        if not (isinstance(chamada.func, ast.Attribute) and chamada.func.attr == "dumps"):
            continue
        for alvo in no.targets:
            if isinstance(alvo, ast.Name):
                mapa[alvo.id] = not _tem_flag(chamada)
    return mapa


def _strings_atribuidas(raiz: ast.AST, *, recursivo: bool) -> dict[str, str]:
    """Nome -> valor, para as atribuicoes de string sob `raiz`."""
    nos = ast.walk(raiz) if recursivo else ast.iter_child_nodes(raiz)
    constantes: dict[str, str] = {}
    for no in nos:
        if not isinstance(no, ast.Assign) or not isinstance(no.value, ast.Constant):
            continue
        if not isinstance(no.value.value, str):
            continue
        for alvo in no.targets:
            if isinstance(alvo, ast.Name):
                constantes[alvo.id] = no.value.value
    return constantes


def _funcao_que_contem(no: ast.AST, pais: dict[int, ast.AST]) -> ast.AST | None:
    """A `def` mais interna que envolve `no`, ou `None` no topo do modulo.

    Precisa existir porque tres agulhas do repo sao variavel LOCAL
    (`sentinela`, `segredo`, `texto_truncado`) -- e `segredo` e atribuida com
    valores diferentes em duas funcoes do mesmo arquivo. Resolver por arquivo
    daria a resposta de outra funcao; resolver por escopo da a certa.
    """
    atual = pais.get(id(no))
    while atual is not None:
        if isinstance(atual, ast.FunctionDef | ast.AsyncFunctionDef):
            return atual
        atual = pais.get(id(atual))
    return None


def _mapa_de_pais(arvore: ast.AST) -> dict[int, ast.AST]:
    pais: dict[int, ast.AST] = {}
    for no in ast.walk(arvore):
        for filho in ast.iter_child_nodes(no):
            pais[id(filho)] = no
    return pais


def _importados_de_mobia(arvore: ast.AST) -> dict[str, str]:
    """Nome -> modulo `mobia.*` de onde ele vem."""
    origem: dict[str, str] = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("mobia"):
            for apelido in no.names:
                origem[apelido.asname or apelido.name] = no.module
    return origem


def _resolver(no: ast.expr, constantes: dict[str, str], importados: dict[str, str]) -> str | None:
    """A agulha, reduzida ao valor. `None` quando nao da para reduzir.

    Tres caminhos, e eles cobrem as 70 assertas que o repo tem hoje: literal,
    constante de topo do proprio arquivo, e constante importada de `mobia.*`
    -- esta ultima resolvida importando o modulo de verdade, que e a unica
    forma de saber o valor de `TEXTO_DO_ENCERRAMENTO_FORA_DE_ESCOPO` sem
    reimplementar o interpretador.
    """
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value
    if isinstance(no, ast.Name):
        if no.id in constantes:
            return constantes[no.id]
        if no.id in importados:
            try:
                return str(getattr(importlib.import_module(importados[no.id]), no.id))
            except (ImportError, AttributeError):
                return None
    return None


def _comparacoes_de_ausencia(arvore: ast.AST) -> list[ast.Compare]:
    """Os `X not in Y`, mais os `X in Y` que vivem dentro de um `not any(...)`.

    A segunda forma existe em `test_turno.py` e em `test_turno_optout.py`:
    `assert not any("lead.qualificado" in r.getMessage() for r in ...)` afirma
    ausencia tanto quanto um `not in`, e uma guarda que so olhasse o operador
    deixaria essa familia inteira de fora.
    """
    achadas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.Compare) and any(isinstance(op, ast.NotIn) for op in no.ops):
            achadas.append(no)
            continue
        negacao = isinstance(no, ast.UnaryOp) and isinstance(no.op, ast.Not)
        if not negacao:
            continue
        for interno in ast.walk(no):
            if isinstance(interno, ast.Compare) and any(
                isinstance(op, ast.In) for op in interno.ops
            ):
                achadas.append(interno)
    return achadas


def _achados_em(fonte: str, caminho: str) -> tuple[list[Achado], list[NaoResolvida]]:
    """As assertas vazias de um arquivo, e as agulhas que nao se deixaram ler.

    **Agulha irresolvivel nao reprova -- e listada.** Mesma assimetria que
    `test_acento_no_texto_ao_lead.py` declara e que a TEC-286 repetiu: errar
    de menos deixa de pegar um caso; errar de mais treina quem le a ignorar a
    guarda. Hoje a lista nasce vazia, porque as 70 agulhas do repo se
    resolvem; se um dia nao nascer, quem ler decide o que fazer.
    """
    arvore = ast.parse(fonte)
    dumps_sem_flag = _dumps_por_variavel(arvore)
    do_modulo = _strings_atribuidas(arvore, recursivo=False)
    importados = _importados_de_mobia(arvore)
    pais = _mapa_de_pais(arvore)
    linhas = fonte.splitlines()

    vazias: list[Achado] = []
    nao_resolvidas: list[NaoResolvida] = []
    for comparacao in _comparacoes_de_ausencia(arvore):
        palheiro = comparacao.comparators[0]
        if not _palheiro_escapado(palheiro, dumps_sem_flag):
            continue
        if MARCA_DE_VACUIDADE_PROPOSITAL in linhas[comparacao.lineno - 1]:
            continue
        funcao = _funcao_que_contem(comparacao, pais)
        constantes = dict(do_modulo)
        if funcao is not None:
            constantes.update(_strings_atribuidas(funcao, recursivo=True))
        agulha = _resolver(comparacao.left, constantes, importados)
        if agulha is None:
            nao_resolvidas.append(
                NaoResolvida(caminho, comparacao.lineno, ast.unparse(comparacao.left))
            )
            continue
        if not agulha.isascii():
            vazias.append(Achado(caminho, comparacao.lineno, agulha))
    return vazias, nao_resolvidas


def _arquivos_de_teste() -> list[Path]:
    return sorted(RAIZ_DOS_TESTES.rglob("test_*.py"))


def test_nenhuma_assercao_de_ausencia_sobre_log_e_vazia() -> None:
    """A guarda, sobre `tests/` inteiro.

    Reprovar aqui nao quer dizer que o codigo esta errado -- quer dizer que a
    asserta apontada nao pode reprovar, e que ela tem de passar por
    `log_legivel(caplog)` (ou `json.dumps(..., ensure_ascii=False)`) para
    voltar a valer.
    """
    vazias = []
    for arquivo in _arquivos_de_teste():
        achados, _ = _achados_em(
            arquivo.read_text(encoding="utf-8"), str(arquivo.relative_to(RAIZ_DOS_TESTES))
        )
        vazias.extend(achados)

    assert not vazias, "assertas que nao podem reprovar (use log_legivel): " + "; ".join(
        f"{a.caminho}:{a.linha} agulha={a.agulha!r}" for a in vazias
    )


def test_a_lista_de_agulhas_irresolviveis_continua_vazia() -> None:
    """Quanto da propria guarda ainda vale.

    Se esta lista crescer, a guarda de cima passou a olhar para menos do que
    diz olhar -- e o numero aqui e a unica coisa que denuncia isso.
    """
    nao_resolvidas = []
    for arquivo in _arquivos_de_teste():
        _, pendentes = _achados_em(
            arquivo.read_text(encoding="utf-8"), str(arquivo.relative_to(RAIZ_DOS_TESTES))
        )
        nao_resolvidas.extend(pendentes)

    assert not nao_resolvidas, "agulhas que a guarda nao soube resolver: " + "; ".join(
        f"{n.caminho}:{n.linha} {n.expressao}" for n in nao_resolvidas
    )


@pytest.mark.parametrize(
    ("fonte", "pega"),
    [
        ('assert "imóvel" not in caplog.text', True),
        ('assert "imovel" not in caplog.text', False),
        ('assert "imóvel" not in log_legivel(caplog)', False),
        ('assert "imóvel" not in json.dumps(corpo)', True),
        ('assert "imóvel" not in json.dumps(corpo, ensure_ascii=False)', False),
        ('assert "imóvel" not in registro.getMessage()', True),
        ('assert not any("imóvel" in r.getMessage() for r in caplog.records)', True),
        ('assert not any("imovel" in r.getMessage() for r in caplog.records)', False),
        ("AGULHA = 'imóvel'\nassert AGULHA not in caplog.text", True),
        ("AGULHA = 'imovel'\nassert AGULHA not in caplog.text", False),
        (
            "from mobia.domain.agente.turno import TEXTO_DO_LIMITE_DE_PERGUNTAS\n"
            "assert TEXTO_DO_LIMITE_DE_PERGUNTAS not in caplog.text",
            True,
        ),
        ("corpo_serializado = json.dumps(c)\nassert 'imóvel' not in corpo_serializado", True),
        (
            "corpo_serializado = json.dumps(c, ensure_ascii=False)\n"
            "assert 'imóvel' not in corpo_serializado",
            False,
        ),
        ('assert "imóvel" not in entregador.entregues[0]', False),
    ],
)
def test_a_guarda_pega_o_caso_e_so_o_caso(fonte: str, pega: bool) -> None:
    """A verificacao nos dois sentidos, e ela mora no repo em vez de ser ritual.

    A nota de metodo da card manda verificar cada sitio nos dois sentidos --
    com o texto plantado, a asserta reprova; sem ele, passa. Plantio manual
    prova isso uma vez e some junto com o plantio. Aqui cada linha da tabela e
    um plantio permanente, e a coluna `pega=False` e o que impede a guarda de
    virar barulho: `log_legivel`, o flag e palheiro que nao e log ficam de
    fora.

    A ultima linha e a fronteira do escopo: `entregador.entregues` e o que o
    LEAD recebeu, nao o log. Nunca passou por `JSONRenderer`, entao acento ali
    e achado normalmente e a guarda nao tem o que dizer.
    """
    achados, nao_resolvidas = _achados_em(fonte, "sintetico.py")
    assert not nao_resolvidas, f"a guarda nao soube ler a agulha: {nao_resolvidas}"
    assert bool(achados) is pega


def test_a_agulha_acentuada_nao_e_achada_em_caplog_text(caplog: Any) -> None:
    """O mecanismo, afirmado em vez de descrito.

    Enquanto este teste passar, `caplog.text` escapa -- e toda asserta de
    ausencia com agulha acentuada feita sobre ele e decoracao. No dia em que
    alguem desligar o escape no renderer (a D1 do desenho, que foi medida e
    recusada por causa do `cp1252` desta maquina), ele reprova e obriga a
    rever esta card inteira, em vez de deixar dois fatos contraditorios
    convivendo no repo.
    """
    configure_logging()
    log = structlog.get_logger()

    with caplog.at_level("INFO"):
        log.info("tec289.prova", texto=AGULHA_ACENTUADA)

    assert caplog.text, "sem log capturado a prova nao vale nada"
    assert AGULHA_ACENTUADA not in caplog.text  # TEC-289: vazia de proposito


def test_a_agulha_acentuada_e_achada_em_log_legivel(caplog: Any) -> None:
    """A outra metade: o helper acha o que `caplog.text` esconde.

    Mesmo log, mesma agulha, resultado oposto -- e a diferenca e so o
    `ensure_ascii=False` de `log_legivel`.
    """
    configure_logging()
    log = structlog.get_logger()

    with caplog.at_level("INFO"):
        log.info("tec289.prova", texto=AGULHA_ACENTUADA)

    assert AGULHA_ACENTUADA in log_legivel(caplog)


def test_a_marca_nao_escapou_deste_arquivo() -> None:
    """A saida da guarda vale para um caso, e ele mora aqui.

    A marca existe porque o teste do mecanismo precisa escrever uma asserta
    vazia de proposito -- e uma guarda com saida que ninguem vigia nao e
    guarda. Se ela aparecer em outro arquivo, alguem silenciou um achado em
    vez de consertar a asserta, e e isso que este teste denuncia.
    """
    com_a_marca = [
        str(arquivo.relative_to(RAIZ_DOS_TESTES))
        for arquivo in _arquivos_de_teste()
        if MARCA_DE_VACUIDADE_PROPOSITAL in arquivo.read_text(encoding="utf-8")
    ]

    assert com_a_marca == [str(Path(__file__).relative_to(RAIZ_DOS_TESTES))]
