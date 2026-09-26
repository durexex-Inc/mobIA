"""Toda funcao que toca `.messages` de um cliente Anthropic esta registrada. TEC-204, D2.

Sem esta guarda, a proxima chamada nasce sem delimitacao e nenhum teste
percebe. Cada sitio esta em uma de tres listas: `DELIMITA`, com o nome do
teste de `test_delimitacao_nos_sitios.py` que prova a delimitacao;
`NAO_RECEBE_TEXTO_DO_LEAD`, com a razao escrita; ou `SO_CONTA_TOKENS`, para o
unico acesso que conta e nao gera. Uma funcao nova em `src/` que toque
`.messages` reprova aqui ate alguem escolher a lista -- e escolher `DELIMITA`
exige um teste que exista.

O casamento e por `ast.Attribute` com `attr == "messages"` em qualquer forma,
nao so `<algo>.messages.create(...)` direto: um apelido (`m = cliente.messages`
ou `self._msgs = cliente.messages`) tambem produz esse mesmo no, na funcao
onde o apelido nasce -- e so daquele ponto que qualquer `.create`/`.stream`/
`.count_tokens` subsequente pode partir. A funcao que atribui o apelido e
o sitio registrado; seguir o apelido ate a chamada de verdade exigiria fluxo
de dados, que uma varredura de `ast` nao faz.
"""

import ast
import pathlib

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SRC = RAIZ / "src"
TESTES_DOS_SITIOS = RAIZ / "tests" / "unit" / "test_delimitacao_nos_sitios.py"

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

# Vazio hoje: toda funcao que gera texto e nao conta recebe algo do lead.
NAO_RECEBE_TEXTO_DO_LEAD: dict[tuple[str, str], str] = {}

SO_CONTA_TOKENS: dict[tuple[str, str], str] = {
    ("mobia/domain/context/resumo.py", "ContadorAnthropic.contar"): (
        "so chama messages.count_tokens: conta, nao gera, e nao obedece a nada"
    ),
}


def _sitios_em(fonte: str, relativo: str) -> set[tuple[str, str]]:
    """`(arquivo, Classe.funcao)` de toda funcao que contem um `ast.Attribute` `.messages`."""
    achados: set[tuple[str, str]] = set()

    def visitar(no: ast.AST, pilha: list[str]) -> None:
        for filho in ast.iter_child_nodes(no):
            if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visitar(filho, [*pilha, filho.name])
                continue
            if isinstance(filho, ast.Attribute) and filho.attr == "messages":
                achados.add((relativo, ".".join(pilha) or "<modulo>"))
            visitar(filho, pilha)

    visitar(ast.parse(fonte), [])
    return achados


def _sitios_que_tocam_messages() -> set[tuple[str, str]]:
    achados: set[tuple[str, str]] = set()
    for arquivo in sorted(SRC.rglob("*.py")):
        relativo = arquivo.relative_to(SRC).as_posix()
        achados |= _sitios_em(arquivo.read_text(encoding="utf-8"), relativo)
    return achados


def test_o_detector_acha_a_forma_que_o_repo_usa() -> None:
    """Sem isto, um detector que nunca acha nada passaria a guarda abaixo vazia.

    Cobre a chamada direta (`C.f`, `g`) e os dois formatos de apelido que
    escapavam do detector antigo: apelido em variavel local (`h`) e apelido
    em atributo de instancia, atribuido num metodo e usado noutro (`D`) -- so
    `D.__init__`, onde `.messages` de fato aparece, e sitio; `D.chamar`, que
    so ve `self._msgs`, nao e.
    """
    fonte = (
        "class C:\n"
        "    async def f(self):\n"
        "        return cast(M, await get_client().messages.create(model='x'))\n"
        "async def g():\n"
        "    await cliente.messages.stream(model='x')\n"
        "    contagem = await cliente.messages.count_tokens(model='x')\n"
        "def h():\n"
        "    mensagens = client.messages\n"
        "    mensagens.create(model='x')\n"
        "class D:\n"
        "    def __init__(self, client):\n"
        "        self._msgs = client.messages\n"
        "    def chamar(self):\n"
        "        self._msgs.create(model='x')\n"
    )

    assert _sitios_em(fonte, "m.py") == {
        ("m.py", "C.f"),
        ("m.py", "g"),
        ("m.py", "h"),
        ("m.py", "D.__init__"),
    }


def test_toda_chamada_ao_modelo_esta_registrada() -> None:
    achados = _sitios_que_tocam_messages()
    registrados = set(DELIMITA) | set(NAO_RECEBE_TEXTO_DO_LEAD) | set(SO_CONTA_TOKENS)

    assert achados - registrados == set(), (
        "sitio que toca .messages sem registro: delimite o texto do lead e ponha o sitio "
        "em DELIMITA com o teste que prova, em NAO_RECEBE_TEXTO_DO_LEAD com a razao, ou em "
        "SO_CONTA_TOKENS quando so conta"
    )
    assert registrados - achados == set(), "sitio registrado que ja nao existe em src/"


def test_todo_sitio_que_delimita_tem_o_teste_que_prova() -> None:
    arvore = ast.parse(TESTES_DOS_SITIOS.read_text(encoding="utf-8"))
    testes = {
        no.name for no in arvore.body if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert set(DELIMITA.values()) <= testes, set(DELIMITA.values()) - testes
