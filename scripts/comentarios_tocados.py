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
            diff, e e exatamente assim que um comentario passa a mentir. A
            saida padrao mostra so os VIZINHO mais proximos da alteracao em
            cada bloco e resume o resto numa linha, porque a listagem inteira
            costuma passar de 100 linhas e deixar de caber numa leitura.

Uso:

    ./.venv/Scripts/python.exe scripts/comentarios_tocados.py
    ./.venv/Scripts/python.exe scripts/comentarios_tocados.py main
    ./.venv/Scripts/python.exe scripts/comentarios_tocados.py main --tudo
"""

import argparse
import ast
import io
import re
import subprocess
import tokenize
from dataclasses import dataclass
from pathlib import Path

# `@@ -antes,n +depois,n @@`. So o lado `+` interessa: sao as linhas como elas
# ficaram, e e contra o arquivo atual que os comentarios sao localizados.
_CABECALHO = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

# O teto de VIZINHOS impressos por bloco na saida padrao.
#
# Medido na TEC-277 sobre 19 branches ja mergeadas (PRs #87 a #108): a saida
# tinha mediana de 890 linhas e maximo de 1928, e 16 das 19 passavam de 100.
# Com este teto a mediana cai para 188.
#
# **5 nao e um otimo, e o joelho de uma curva plana.** Medido para 3, 5, 10 e
# 20, a diferenca de itens omitidos entre 3 e 20 e de ~9%: o volume nao vem de
# poucos blocos com muitos achados, vem de MUITOS blocos batendo o teto. Como
# 3 e 5 custam quase o mesmo, 5 e o maior que nao paga nada a mais.
#
# O teto existe porque nao ha regra melhor, e isso foi medido, nao suposto:
# 75,9% do ruido sai de `executar_turno`, que tem 1877 linhas. Uma regra de
# vizinhanca por distancia deixaria 65,9% de pe num raio de 50 linhas, e
# "menor bloco que contem a linha alterada" rende 0,036%. Enquanto aquela
# funcao existir, esta saida vive de teto -- ver a L1 do desenho.
MAXIMO_DE_VIZINHOS_POR_BLOCO = 5


@dataclass(frozen=True)
class Achado:
    linha: int
    texto: str
    alterado: bool
    # Distancia em linhas ate a alteracao mais proxima do mesmo arquivo, e o
    # nome do menor bloco MEXIDO que contem este achado -- um achado dentro de
    # um metodo intocado nao tem candidato proprio e herda o nome da classe
    # mexida. Os dois existem para o teto de `main`: `distancia` ordena quem
    # fica, `bloco` agrupa e nomeia o que foi omitido. Um ALTERADO tem
    # distancia 0 e bloco vazio -- o teto nao o alcanca, entao nao precisa de
    # nenhum dos dois.
    distancia: int = 0
    bloco: str = ""


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


def _blocos(arvore: ast.AST) -> list[tuple[int, int, str]]:
    """Faixa de linhas e nome de cada def/class, para decidir o que e VIZINHO.

    O def e a unidade certa: e o escopo que um comentario costuma descrever.
    Usar o arquivo inteiro marcaria comentario nenhum como seguro, e usar so as
    linhas coladas perderia o comentario de topo de funcao, que e justamente o
    que envelhece quando o corpo dela muda.

    O nome nao entra na classificacao -- entra no teto de `main`, que precisa
    dizer em QUAL bloco ficaram os vizinhos que ele omitiu. Sem ele a linha de
    resumo seria "+703 vizinhos omitidos", que nao diz onde procurar.
    """
    faixas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            faixas.append((no.lineno, no.end_lineno or no.lineno, no.name))
    return faixas


def examinar(arquivo: Path, alteradas: set[int]) -> list[Achado]:
    try:
        fonte = arquivo.read_text(encoding="utf-8")
        arvore = ast.parse(fonte)
    except (OSError, SyntaxError):
        return []

    blocos = [(i, f, n) for i, f, n in _blocos(arvore) if any(i <= x <= f for x in alteradas)]

    def dentro_de_bloco_mexido(inicio: int, fim: int) -> bool:
        return any(i <= inicio and fim <= f for i, f, _ in blocos)

    def distancia(inicio: int, fim: int) -> int:
        # Da borda mais proxima da faixa, nao da primeira linha. Para uma
        # docstring longa isso importa: medir sempre da primeira linha faria
        # uma alteracao colada no fim dela parecer distante.
        return min(min(abs(n - inicio), abs(n - fim)) for n in alteradas)

    def dono(inicio: int, fim: int) -> str:
        # O MENOR bloco MEXIDO que contem o achado -- "blocos" ja veio filtrado
        # para quem tem linha alterada, entao um achado dentro de um metodo
        # intocado nao tem candidato proprio e herda o nome da classe mexida.
        # Usar o maior bloco sempre diria "+703 em C" para um comentario que
        # esta em `C.m`, e quem le nao saberia onde procurar. Isto e
        # atribuicao, nao classificacao: o desenho mediu que trocar a
        # classificacao para o menor bloco rende 0,036%.
        candidatos = [(f - i, n) for i, f, n in blocos if i <= inicio and fim <= f]
        return min(candidatos)[1] if candidatos else ""

    achados = []
    for linha, texto in _comentarios(fonte):
        if linha in alteradas:
            achados.append(Achado(linha, texto, alterado=True))
        elif dentro_de_bloco_mexido(linha, linha):
            achados.append(Achado(linha, texto, False, distancia(linha, linha), dono(linha, linha)))
    for inicio, fim, texto in _docstrings(arvore):
        if any(n in alteradas for n in range(inicio, fim + 1)):
            achados.append(Achado(inicio, texto, alterado=True))
        elif dentro_de_bloco_mexido(inicio, fim):
            achados.append(Achado(inicio, texto, False, distancia(inicio, fim), dono(inicio, fim)))
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


def limitar(achados: list[Achado], *, teto: int) -> tuple[list[Achado], dict[str, int]]:
    """Os achados que ficam, e quantos ficaram de fora em cada bloco.

    `teto` de 0 desliga o corte: e assim que `--tudo` e implementado, sem um
    caminho separado que possa divergir do normal.

    ALTERADO nunca e cortado. A obrigacao sobre ele e de outra natureza -- e o
    comentario que quem abre o PR acabou de tocar --, e o teto existe contra
    ruido de vizinhanca. **Consequencia declarada:** numa branch que reescreve
    muito, e ALTERADO que domina o que resta (a TEC-153 tem 623 e a TEC-184,
    525), e a saida continua longa apesar do teto.

    Ordena por distancia para ESCOLHER e por linha para DEVOLVER: a escolha
    quer os mais perto da alteracao, a saida quer ser navegavel de cima para
    baixo no arquivo.
    """
    if teto <= 0:
        return achados, {}

    # Chaveado pelo NOME do bloco, nao pela faixa de linhas: dois def/class
    # homonimos no mesmo arquivo caem no mesmo balde e dividem um teto so, e a
    # linha de resumo nao diz qual dos dois. A CONTAGEM final continua certa
    # nos dois; o que fica ambiguo e so "quais 5" e "onde". Medido: 0 casos num
    # range de 18 commits e 1 caso num de 40, e nesse 1 nada se perdeu.
    # Chavear por faixa exigiria Achado carregar a faixa do bloco, e o ganho
    # medido nao paga o custo.
    por_bloco: dict[str, list[Achado]] = {}
    ficam = [a for a in achados if a.alterado]
    for achado in achados:
        if not achado.alterado:
            por_bloco.setdefault(achado.bloco, []).append(achado)

    omitidos = {}
    for bloco, do_bloco in por_bloco.items():
        # `a.linha` desempata distancia igual, para a escolha ser estavel entre
        # execucoes em vez de depender da ordem de `ast.walk`.
        ordenados = sorted(do_bloco, key=lambda a: (a.distancia, a.linha))
        ficam.extend(ordenados[:teto])
        # `> 0`, nao truthiness: um inteiro negativo e verdadeiro em Python, e
        # um bloco com menos vizinhos que o teto daria `sobrando` negativo.
        if (sobrando := len(ordenados) - teto) > 0:
            omitidos[bloco] = sobrando

    return sorted(ficam, key=lambda a: a.linha), omitidos


def main() -> int:
    analisador = argparse.ArgumentParser(
        description="Lista comentarios e docstrings que a branch precisa reconferir."
    )
    analisador.add_argument(
        "base",
        nargs="?",
        default="origin/main",
        help="ref de comparacao (branch, commit ou tag); default origin/main",
    )
    analisador.add_argument(
        "--tudo",
        action="store_true",
        help="imprime todos os vizinhos, sem o teto por bloco",
    )
    argumentos = analisador.parse_args()
    base = argumentos.base
    teto = 0 if argumentos.tudo else MAXIMO_DE_VIZINHOS_POR_BLOCO
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
        ficam, omitidos = limitar(achados, teto=teto)
        print(f"\n{arquivo}")
        for achado in ficam:
            marca = "ALTERADO" if achado.alterado else "VIZINHO "
            texto = achado.texto if len(achado.texto) <= 96 else achado.texto[:93] + "..."
            print(f"  {marca} {arquivo}:{achado.linha}  {texto}")
            if achado.alterado:
                alterados += 1
            else:
                vizinhos += 1
        for bloco, quantos in sorted(omitidos.items()):
            # Conta o que EXISTE, nao o que coube na tela -- senao o resumo
            # mente sobre o proprio tamanho da listagem que omitiu.
            vizinhos += quantos
            print(
                f"  ... +{quantos} vizinho(s) em {bloco}, os mais distantes omitidos -- use --tudo"
            )

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
