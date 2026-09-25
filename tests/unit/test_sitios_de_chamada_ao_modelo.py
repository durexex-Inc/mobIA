"""Toda chamada que gera texto num modelo esta registrada. TEC-204, D2.

Sem esta guarda, a proxima chamada nasce sem delimitacao e nenhum teste
percebe. Cada sitio esta em uma de duas listas: `DELIMITA`, com o nome do
teste de `test_delimitacao_nos_sitios.py` que prova a delimitacao, ou
`NAO_RECEBE_TEXTO_DO_LEAD`, com a razao escrita. Uma chamada nova em `src/`
reprova aqui ate alguem escolher a lista -- e escolher `DELIMITA` exige um
teste que exista.

`count_tokens` fica de fora: conta, nao gera, e nao obedece a nada.
"""

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
TESTES_DOS_SITIOS = RAIZ / "tests" / "unit" / "test_delimitacao_nos_sitios.py"

_METODOS_QUE_GERAM = frozenset({"create", "stream"})

DELIMITA: dict[tuple[str, str], str] = {
    (
        "mobia/domain/agente/classificador.py",
        "ClassificadorAnthropic._chamar",
    ): "test_o_turno_principal_delimita_o_lead",
    ("mobia/infra/moderacao.py", "ModeradorAnthropic.moderar"): (
        "test_a_moderacao_delimita_o_que_julga"
    ),
    ("mobia/domain/context/resumo.py", "ResumidorAnthropic.resumir"): (
        "test_a_dobra_do_resumo_delimita_o_lead_e_o_resumo"
    ),
    ("mobia/domain/handoff/resumo.py", "RedatorAnthropic._chamar"): (
        "test_o_resumo_do_handoff_delimita_a_regiao"
    ),
    ("mobia/domain/followup/prosa.py", "redigir_abertura"): (
        "test_a_abertura_do_followup_delimita_o_resumo"
    ),
}

# Vazio hoje: toda chamada que gera texto recebe algo do lead.
NAO_RECEBE_TEXTO_DO_LEAD: dict[tuple[str, str], str] = {}


def _chamadas_em(fonte: str, relativo: str) -> set[tuple[str, str]]:
    """`(arquivo, Classe.funcao)` de cada `<algo>.messages.create(...)` ou `.stream(...)`."""
    achadas: set[tuple[str, str]] = set()

    def visitar(no: ast.AST, pilha: list[str]) -> None:
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visitar(filho, [*pilha, filho.name])
                continue
            if (
                isinstance(filho, ast.Call)
                and isinstance(filho.func, ast.Attribute)
                and filho.func.attr in _METODOS_QUE_GERAM
                and isinstance(filho.func.value, ast.Attribute)
                and filho.func.value.attr == "messages"
            ):
                achadas.add((relativo, ".".join(pilha) or "<modulo>"))
            visitar(filho, pilha)

    visitar(ast.parse(fonte), [])
    return achadas


def _chamadas_ao_modelo() -> set[tuple[str, str]]:
    achadas: set[tuple[str, str]] = set()
    for arquivo in sorted(SRC.rglob("*.py")):
        relativo = arquivo.relative_to(SRC).as_posix()
        achadas |= _chamadas_em(arquivo.read_text(encoding="utf-8"), relativo)
    return achadas


def test_o_detector_acha_a_forma_que_o_repo_usa() -> None:
    """Sem isto, um detector que nunca acha nada passaria a guarda abaixo vazia."""
    fonte = (
        "class C:\n"
        "    async def f(self):\n"
        "        return cast(M, await get_client().messages.create(model='x'))\n"
        "async def g():\n"
        "    await cliente.messages.stream(model='x')\n"
        "    await cliente.messages.count_tokens(model='x')\n"
    )

    assert _chamadas_em(fonte, "m.py") == {("m.py", "C.f"), ("m.py", "g")}


def test_toda_chamada_ao_modelo_esta_registrada() -> None:
    achadas = _chamadas_ao_modelo()
    registradas = set(DELIMITA) | set(NAO_RECEBE_TEXTO_DO_LEAD)

    assert achadas - registradas == set(), (
        "chamada ao modelo sem registro: delimite o texto do lead e ponha o sitio "
        "em DELIMITA com o teste que prova, ou em NAO_RECEBE_TEXTO_DO_LEAD com a razao"
    )
    assert registradas - achadas == set(), "sitio registrado que ja nao existe em src/"


def test_todo_sitio_que_delimita_tem_o_teste_que_prova() -> None:
    arvore = ast.parse(TESTES_DOS_SITIOS.read_text(encoding="utf-8"))
    testes = {
        no.name for no in arvore.body if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert set(DELIMITA.values()) <= testes, set(DELIMITA.values()) - testes
