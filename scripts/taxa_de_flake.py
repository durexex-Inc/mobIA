"""Mede a taxa de falha EM ISOLAMENTO dos arquivos que o CLAUDE.md nomeia.

O CLAUDE.md manda rodar o arquivo sozinho antes de atribuir uma falha de
integracao a uma mudanca sua. Ate a TEC-268 ele sustentava essa instrucao
afirmando que quatro arquivos "passam 100% em isolamento", sem condicao
nenhuma -- e a propriedade **depende da maquina**.

Foi o que a TEC-268 mediu: em 09/09/2026, na maquina anterior, uma execucao
isolada de `test_dedup_por_message_id.py` reprovou 3 de 5 com erro de Redis; em
20/09/2026, em outra maquina, 75 execucoes isoladas dos quatro arquivos deram
zero falhas. As duas medicoes estao certas, e e por isso que o CLAUDE.md passou
a datar e atribuir cada uma em vez de afirmar a propriedade sem condicao.

Este script existe para que a proxima pessoa que duvidar nao precise remontar a
medicao: a pergunta "isso ainda vale nesta maquina?" custa um comando e ~13
minutos, em vez de uma sessao inteira. E a licao que a TEC-276 cobrou no mesmo
dia -- numero medido que vive so em prosa nao se deixa re-derivar, e tres
pessoas derivam tres resultados.

**Nao e gate e nao reprova nada.** Ele imprime a contagem; quem le decide. Exige
os containers de pe (`docker compose up -d`), porque so mede o que de fato roda
contra Postgres e Redis.

    ./.venv/Scripts/python.exe scripts/taxa_de_flake.py
    ./.venv/Scripts/python.exe scripts/taxa_de_flake.py --vezes 5
    ./.venv/Scripts/python.exe scripts/taxa_de_flake.py \
        --arquivo tests/features/test_dedup_por_message_id.py
"""

import argparse
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Os quatro que o CLAUDE.md nomeia, e so eles: este script mede a afirmacao que
# esta escrita la, nao procura flake novo. Acrescentar um arquivo aqui sem
# acrescenta-lo la faria o script medir uma coisa e a prosa afirmar outra.
ARQUIVOS_DO_CLAUDE_MD = (
    "tests/features/test_dedup_por_message_id.py",
    "tests/integration/test_montagem.py",
    "tests/integration/test_sweep_stalled.py",
    "tests/integration/test_optout_repositorio.py",
)

VEZES_PADRAO = 15

# `-p no:cacheprovider` para uma execucao nao herdar o `.pytest_cache` da
# anterior: com `--lf` ou `--ff` na cabeca de alguem, a ordem mudaria entre
# repeticoes e as amostras deixariam de ser comparaveis.
ARGUMENTOS_DO_PYTEST = ("-q", "--tb=line", "-p", "no:cacheprovider")

_RESUMO = re.compile(r"(\d+) (passed|failed|error)", re.MULTILINE)


@dataclass
class Amostra:
    """O resultado de UMA execucao isolada de um arquivo."""

    passou: bool
    duracao: float
    resumo: str
    reprovados: list[str] = field(default_factory=list)


def _executar(arquivo: str) -> Amostra:
    inicio = time.perf_counter()
    processo = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", arquivo, *ARGUMENTOS_DO_PYTEST],
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    duracao = time.perf_counter() - inicio
    saida = processo.stdout + processo.stderr
    reprovados = [
        linha.split("::")[-1].split(" ")[0]
        for linha in saida.splitlines()
        if linha.startswith(("FAILED", "ERROR"))
    ]
    resumos = _RESUMO.findall(saida)
    resumo = ", ".join(f"{quantos} {estado}" for quantos, estado in resumos) or "sem resumo"
    return Amostra(
        passou=processo.returncode == 0, duracao=duracao, resumo=resumo, reprovados=reprovados
    )


def medir(arquivos: tuple[str, ...], vezes: int) -> int:
    """Roda cada arquivo `vezes` vezes, sozinho, e imprime a contagem.

    Devolve o total de execucoes que falharam -- util para quem quiser
    encadear, ainda que o script nao seja gate.
    """
    total_de_falhas = 0
    for arquivo in arquivos:
        print(f"\n### {arquivo} -- {vezes} execucoes isoladas")
        falhas = 0
        duracoes = []
        for i in range(1, vezes + 1):
            amostra = _executar(arquivo)
            duracoes.append(amostra.duracao)
            if not amostra.passou:
                falhas += 1
                print(f"  {i:02d} FALHOU ({amostra.resumo}): {' '.join(amostra.reprovados)}")
        media = sum(duracoes) / len(duracoes) if duracoes else 0.0
        print(f"  {vezes - falhas}/{vezes} passaram, {media:.1f}s em media por execucao")
        total_de_falhas += falhas

    print(f"\nTOTAL: {total_de_falhas} execucao(oes) com falha")
    if total_de_falhas:
        print(
            "A afirmacao do CLAUDE.md sobre isolamento NAO vale nesta maquina. "
            "Atualize a secao 'Testes' com esta medicao, a data e a maquina -- "
            "nao apague a anterior."
        )
    return total_de_falhas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vezes",
        type=int,
        default=VEZES_PADRAO,
        help=f"execucoes por arquivo (padrao: {VEZES_PADRAO})",
    )
    parser.add_argument(
        "--arquivo",
        action="append",
        help="mede so este arquivo; repetivel. Sem isto, mede os quatro do CLAUDE.md",
    )
    argumentos = parser.parse_args()
    arquivos = tuple(argumentos.arquivo) if argumentos.arquivo else ARQUIVOS_DO_CLAUDE_MD
    medir(arquivos, argumentos.vezes)
    # Sempre 0: medicao nao reprova ninguem. Ver o docstring do modulo.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
