"""A arvore de migrations tem uma cabeca so. TEC-370.

**Este arquivo existe porque o defeito que ele pega nao aparece em PR nenhum.**
Duas branches saem da mesma revisao e cada uma numera a sua com o proximo
inteiro. Na arvore de cada uma ha uma cabeca so, entao as duas passam em tudo;
o conflito nasce no SEGUNDO merge, numa arvore que ninguem rodou. A partir dali
`alembic upgrade head` reprova com "Multiple head revisions are present" e
**todo** teste de integracao morre no setup de `migrar_banco` -- sem que nenhum
dos dois autores tenha feito nada errado.

Aconteceu duas vezes em 24/09/2026: `0044_agendamentos` (TEC-168) contra
`0044_usuarios_e_sessoes` (TEC-201), e horas depois `0045_usuarios_e_sessoes`
contra `0045_motivo_da_alocacao` (TEC-166).

**Le os ARQUIVOS com `ast`, e nao o `ScriptDirectory` do alembic.** Duas razoes,
e as duas importam:

- O `alembic` **deduplica** revisao repetida -- ele avisa `Revision 0045 is
  present more than once` e segue com uma delas. Quem pergunta a ele nao
  consegue nomear os dois ARQUIVOS em conflito, que e justamente o que quem
  reprova precisa saber para consertar.
- Ler arquivo nao precisa de banco nem de configuracao, entao este gate vale em
  `tests/unit` -- antes de a fixture de banco sequer tentar subir. Um gate que
  so decide com o Postgres de pe chegaria tarde demais.
"""

import ast
import pathlib

VERSIONS = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _atribuicao_de(arvore: ast.Module, nome: str) -> str | None:
    """O valor literal de `nome = "..."` no topo do modulo, ou None.

    So atribuicao de literal de string: `down_revision = None` (a primeira
    migration) devolve None, que e o que se quer -- ela e a raiz e nao aponta
    para ninguem.
    """
    for no in arvore.body:
        if not isinstance(no, ast.Assign):
            continue
        for alvo in no.targets:
            if isinstance(alvo, ast.Name) and alvo.id == nome:
                if isinstance(no.value, ast.Constant) and isinstance(no.value.value, str):
                    return no.value.value
                return None
    return None


def _migrations() -> list[tuple[str, str | None, str]]:
    """`(revision, down_revision, nome do arquivo)` de cada migration."""
    achadas = []
    for caminho in sorted(VERSIONS.glob("*.py")):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        revisao = _atribuicao_de(arvore, "revision")
        if revisao is None:
            continue
        achadas.append((revisao, _atribuicao_de(arvore, "down_revision"), caminho.name))
    return achadas


def test_nenhuma_revisao_aparece_duas_vezes() -> None:
    """Duas migrations chamadas `0045` sao duas migrations sem nome proprio.

    E o sintoma que o `alembic` avisa e engole: ele fica com uma delas, e a
    outra some da arvore -- o que significa que o DDL dela **nunca roda**,
    mesmo com o `upgrade` reportando sucesso, se o conflito de cabecas for
    resolvido por fora.
    """
    por_revisao: dict[str, list[str]] = {}
    for revisao, _, arquivo in _migrations():
        por_revisao.setdefault(revisao, []).append(arquivo)

    repetidas = {rev: arqs for rev, arqs in por_revisao.items() if len(arqs) > 1}

    assert not repetidas, "revisao repetida em mais de um arquivo: " + "; ".join(
        f"{rev} em {', '.join(arqs)}" for rev, arqs in sorted(repetidas.items())
    )


def test_a_arvore_de_migrations_tem_uma_cabeca_so() -> None:
    """Cabeca e a revisao que ninguem aponta como `down_revision`.

    Duas cabecas sao duas migrations irmas -- as duas saindo da mesma revisao
    --, e o conserto e sempre o mesmo: a que MERGEAR POR ULTIMO se renumera
    para o proximo inteiro e aponta o `down_revision` dela para a outra. O
    conteudo das duas nao muda.
    """
    migrations = _migrations()
    apontadas = {baixo for _, baixo, _ in migrations if baixo is not None}
    cabecas = [(rev, arq) for rev, _, arq in migrations if rev not in apontadas]

    assert len(cabecas) == 1, (
        "a arvore de migrations tem "
        + str(len(cabecas))
        + " cabecas, e `alembic upgrade head` vai reprovar com "
        '"Multiple head revisions are present" -- derrubando TODO teste de '
        "integracao no setup de `migrar_banco`. Cabecas: "
        + "; ".join(f"{rev} ({arq})" for rev, arq in sorted(cabecas))
        + ". Conserto: renumere a que mergeou por ultimo para o proximo inteiro "
        "e aponte o `down_revision` dela para a outra."
    )


def test_todo_down_revision_aponta_para_uma_revisao_que_existe() -> None:
    """Elo quebrado some do caminho do `upgrade` sem dizer nada.

    Nao e o defeito que motivou esta card, e entra junto pelo mesmo argumento:
    e a outra forma de a cadeia estar errada, custa tres linhas conferir, e o
    sintoma dela (DDL que nunca roda) e ainda mais silencioso que o de duas
    cabecas.
    """
    existentes = {rev for rev, _, _ in _migrations()}
    quebrados = [
        f"{arq} aponta para `{baixo}`"
        for _, baixo, arq in _migrations()
        if baixo is not None and baixo not in existentes
    ]

    assert not quebrados, "down_revision aponta para revisao que nao existe: " + "; ".join(
        quebrados
    )


def test_ha_exatamente_uma_raiz() -> None:
    """A raiz e a unica com `down_revision = None`.

    Duas raizes sao duas arvores separadas -- o mesmo estrago de duas cabecas,
    visto pela outra ponta, e o modo de falha de quem cria uma migration
    copiando a PRIMEIRA do projeto em vez da ultima.
    """
    raizes = [arq for _, baixo, arq in _migrations() if baixo is None]

    assert len(raizes) == 1, f"a arvore tem {len(raizes)} raizes: {sorted(raizes)}"
