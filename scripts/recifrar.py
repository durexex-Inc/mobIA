"""Recifra com a chave ativa todo blob do banco gravado sob outra chave. TEC-203, D1.

E o penultimo passo para TIRAR uma chave do keyring (o ultimo e conferir que a
saida deu zero e so entao apagar a chave de `content_encryption_keys`). Roda
com o servico de pe -- ver `mobia.admin.recifrar` e `docs/seguranca/segredos.md`.

**O zero de "blobs fora da chave ativa" vem de uma LEITURA separada, depois
da escrita, nunca do relatorio da propria escrita.** O relatorio de quem
escreveu bucketiza tudo sob a ativa por construcao -- o que ja estava e o que
acabou de ser reescrito caem no mesmo balde --, entao ele da zero mesmo se a
escrita tiver parado de escanear cedo (por exemplo um bug de paginacao). So a
leitura de verificacao, que conta nao mexe em nada, enxerga isso.

Uso:
    ./.venv/Scripts/python.exe scripts/recifrar.py               # recifra de fato
    ./.venv/Scripts/python.exe scripts/recifrar.py --so-contar   # so relata, nao escreve
"""

import argparse
import asyncio
import sys

from mobia.admin.recifrar import recifrar
from mobia.infra.crypto import id_da_chave_ativa
from mobia.infra.db import dispose_engine, get_sessionmaker


def _fora_da_ativa(relatorio: dict[str, dict[int | None, int]], ativa: int | None) -> int:
    return sum(
        v for por_chave in relatorio.values() for chave, v in por_chave.items() if chave != ativa
    )


async def _executar(*, so_contar: bool) -> int:
    """A logica async, separada de `main` para o teste chamar direto.

    Mesma razao de `mobia.admin.reativar._executar`: `main` chama
    `asyncio.run`, e um teste async ja roda dentro de um loop.
    """
    ativa = id_da_chave_ativa()
    sessionmaker = get_sessionmaker()
    relatorio = await recifrar(sessionmaker, so_contar=so_contar)
    for coluna, por_chave in relatorio.items():
        print(f"{coluna}: {por_chave}")

    # Em `--so-contar` o relatorio acima JA E a leitura de verificacao (nada
    # foi escrito). Escrevendo de fato, ele nao prova nada -- ver a docstring
    # do modulo --, entao uma segunda passada, so leitura, roda depois.
    relatorio_de_verificacao = (
        relatorio if so_contar else await recifrar(sessionmaker, so_contar=True)
    )
    await dispose_engine()
    print(
        "blobs fora da chave ativa (leitura de verificacao): "
        f"{_fora_da_ativa(relatorio_de_verificacao, ativa)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Recifra com a chave ativa todo blob gravado sob outra chave."
    )
    parser.add_argument(
        "--so-contar",
        action="store_true",
        help="so relata quantos blobs ha por chave, sem escrever nada",
    )
    args = parser.parse_args(argv)

    return asyncio.run(_executar(so_contar=args.so_contar))


if __name__ == "__main__":
    sys.exit(main())
