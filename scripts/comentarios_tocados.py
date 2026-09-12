"""Lista os comentarios e docstrings que a branch precisa reconferir.

Este repo trata comentario desatualizado como defeito, nao como sujeira, e a
regra esta escrita no CLAUDE.md ("Comentario nao mente"). Mesmo assim, ~51
commits do historico existem so para corrigir afirmacao que o proprio repo
escreveu errado antes -- e a TEC-146 registra o caso caro: um comentario em
`_faixa_de` justificava a ordem de duas checagens com um perigo inexistente,
escondeu um bug de orcamento 40% abaixo do informado, e sobreviveu a duas
rodadas de revisao porque quem lia acreditava nele.

Nenhum dos tres gates estaticos olha para comentario. Este script nao vira gate
tambem: ele nao valida nada e nao reprova nada. Ele so poe na frente de quem
revisa a lista exata do que precisa ser reconferido, para que a verificacao pare
de depender de alguem lembrar.

Duas categorias, e a segunda e a que pega o defeito da TEC-146:

  ALTERADO  o comentario mudou nesta branch. Releia o codigo e confirme que ele
            ainda descreve o que esta ali.

  VIZINHO   o comentario NAO mudou, mas o codigo dentro do mesmo def/class
            mudou. E o caso perigoso: ninguem olha para o que nao aparece no
            diff, e e exatamente assim que um comentario passa a mentir.

Uso:

    ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
    ./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
"""

import ast
import io
import re
import subprocess
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

# `@@ -antes,n +depois,n @@`. So o lado `+` interessa: sao as linhas como elas
# ficaram, e e contra o arquivo atual que os comentarios sao localizados.
_CABECALHO = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Achado:
    linha: int
    texto: str
    alterado: bool


def _rodar(*argumentos: str) -> str:
    resultado = subprocess.run(
        ["git", *argumentos], capture_output=True, text=True, encoding="utf-8"
    )
    if resultado.returncode != 0:
        raise SystemExit(f"git {' '.join(argumentos)} falhou:\n{resultado.stderr}")
    return resultado.stdout


def linhas_alteradas(base: str) -> dict[Path, set[int]]:
    """Por arquivo .py, as linhas que esta branch acrescentou ou mexeu.

    `--unified=0` porque aqui nao se quer contexto: uma linha so entra se o diff
    de fato a tocou. Com o contexto padrao de 3 linhas, todo comentario vizinho
    de qualquer mudanca entraria como ALTERADO e a distincao que este script
    existe para fazer desapareceria.
    """
    saida = _rodar("diff", "--unified=0", f"{base}...HEAD", "--", "*.py")
    por_arquivo: dict[Path, set[int]] = {}
    atual: set[int] | None = None
    for linha in saida.splitlines():
        if linha.startswith("+++ b/"):
            atual = por_arquivo.setdefault(Path(linha[6:]), set())
        elif linha.startswith("+++ /dev/null"):
            atual = None
        elif atual is not None and (casa := _CABECALHO.match(linha)):
            inicio = int(casa.group(1))
            # Grupo 2 ausente significa uma linha so; `,0` significa remocao
            # pura, que nao deixa linha nova para reconferir.
            quantas = int(casa.group(2)) if casa.group(2) is not None else 1
            atual.update(range(inicio, inicio + quantas))
    return {arquivo: linhas for arquivo, linhas in por_arquivo.items() if linhas}


def _comentarios(fonte: str) -> list[tuple[int, str]]:
    """Todo `#` do arquivo, por `tokenize` e nao por regex.

    Um `#` dentro de string nao e comentario, e distinguir os dois com expressao
    regular e onde esse tipo de script costuma errar em silencio.
    """
    achados = []
    try:
        for ficha in tokenize.generate_tokens(io.StringIO(fonte).readline):
            if ficha.type == tokenize.COMMENT:
                achados.append((ficha.start[0], ficha.string.strip()))
    except (tokenize.TokenError, IndentationError):
        # Arquivo que nao tokeniza nao tem comentario localizavel. O ruff ja
        # reprova antes disso; aqui so nao vale derrubar a listagem inteira.
        return []
    return achados


def _docstrings(arvore: ast.AST) -> list[tuple[int, int, str]]:
    """Cada docstring como (primeira linha, ultima linha, primeira frase)."""
    achados = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        corpo = getattr(no, "body", None)
        if not corpo:
            continue
        primeiro = corpo[0]
        if not (
            isinstance(primeiro, ast.Expr)
            and isinstance(primeiro.value, ast.Constant)
            and isinstance(primeiro.value.value, str)
        ):
            continue
        texto = primeiro.value.value.strip().splitlines()
        achados.append(
            (
                primeiro.lineno,
                primeiro.end_lineno or primeiro.lineno,
                f'"""{texto[0] if texto else ""}',
            )
        )
    return achados


def _blocos(arvore: ast.AST) -> list[tuple[int, int]]:
    """Faixa de linhas de cada def/class, para decidir o que e VIZINHO.

    O def e a unidade certa: e o escopo que um comentario costuma descrever.
    Usar o arquivo inteiro marcaria comentario nenhum como seguro, e usar so as
    linhas coladas perderia o comentario de topo de funcao, que e justamente o
    que envelhece quando o corpo dela muda.
    """
    faixas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            faixas.append((no.lineno, no.end_lineno or no.lineno))
    return faixas


def examinar(arquivo: Path, alteradas: set[int]) -> list[Achado]:
    try:
        fonte = arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
    except (OSError, SyntaxError):
        return []

    blocos = [(i, f) for i, f in _blocos(arvore) if any(i <= n <= f for n in alteradas)]

    def dentro_de_bloco_mexido(inicio: int, fim: int) -> bool:
        return any(i <= inicio and fim <= f for i, f in blocos)

    achados = []
    for linha, texto in _comentarios(fonte):
        if linha in alteradas:
            achados.append(Achado(linha, texto, alterado=True))
        elif dentro_de_bloco_mexido(linha, linha):
            achados.append(Achado(linha, texto, alterado=False))
    for inicio, fim, texto in _docstrings(arvore):
        if any(n in alteradas for n in range(inicio, fim + 1)):
            achados.append(Achado(inicio, texto, alterado=True))
        elif dentro_de_bloco_mexido(inicio, fim):
            achados.append(Achado(inicio, texto, alterado=False))
    return sorted(achados, key=lambda a: a.linha)


def _pendentes_fora_do_commit() -> list[str]:
    """Arquivos .py modificados ou nao rastreados que o diff nao enxerga.

    `git diff base...HEAD` compara commits, entao trabalho ainda nao commitado
    fica invisivel para ele. Sem este aviso, rodar o script com a arvore suja
    responde "nenhum arquivo mudou" -- uma falsa tranquilidade pior que nao ter
    rodado, porque quem le acredita.
    """
    saida = _rodar("status", "--porcelain", "--untracked-files=all")
    return sorted(
        linha[3:] for linha in saida.splitlines() if linha[3:].endswith(".py") and linha[3:]
    )


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    por_arquivo = linhas_alteradas(base)

    if pendentes := _pendentes_fora_do_commit():
        print(f"AVISO: {len(pendentes)} arquivo(s) .py fora de commit, invisiveis para o diff:")
        for caminho in pendentes:
            print(f"  {caminho}")
        print("Commite antes de confiar nesta listagem.\n")

    if not por_arquivo:
        print(f"Nenhum arquivo .py commitado mudou em relacao a {base}.")
        return 0

    alterados = vizinhos = 0
    for arquivo in sorted(por_arquivo):
        achados = examinar(arquivo, por_arquivo[arquivo])
        if not achados:
            continue
        print(f"\n{arquivo}")
        for achado in achados:
            marca = "ALTERADO" if achado.alterado else "VIZINHO "
            texto = achado.texto if len(achado.texto) <= 96 else achado.texto[:93] + "..."
            print(f"  {marca} {arquivo}:{achado.linha}  {texto}")
            if achado.alterado:
                alterados += 1
            else:
                vizinhos += 1

    if not alterados and not vizinhos:
        print(f"Nenhum comentario ou docstring a reconferir em relacao a {base}.")
        return 0

    print(
        f"\n{alterados} alterado(s) nesta branch, {vizinhos} vizinho(s) de codigo que mudou.\n"
        "VIZINHO e o que nao aparece no diff: confira se ainda descreve o codigo."
    )
    # Sempre 0: este script informa, nao reprova. Virar gate exigiria decidir
    # automaticamente se um comentario esta certo, que e o julgamento que ele
    # existe justamente para devolver a uma pessoa.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
