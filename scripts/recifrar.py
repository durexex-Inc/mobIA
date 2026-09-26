"""Recifra com a chave ativa todo blob do banco gravado sob outra chave. TEC-203, D1.

E o penultimo passo para TIRAR uma chave do keyring (o ultimo e conferir que a
saida deu zero e so entao apagar a chave de `content_encryption_keys`). Roda
com o servico de pe -- ver `mobia.admin.recifrar` e `docs/seguranca/segredos.md`.

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


async def _executar(*, so_contar: bool) -> int:
    """A logica async, separada de `main` para o teste chamar direto.

    Mesma razao de `mobia.admin.reativar._executar`: `main` chama
    `asyncio.run`, e um teste async ja roda dentro de um loop.
    """
    ativa = id_da_chave_ativa()
    relatorio = await recifrar(get_sessionmaker(), so_contar=so_contar)
    fora_da_ativa = 0
    for coluna, por_chave in relatorio.items():
        print(f"{coluna}: {por_chave}")
        # Com `so_contar`, `por_chave` e a foto de antes de reescrever, e
        # tudo que nao esteja na chave ativa ainda precisa da recifra. Sem
        # `so_contar`, o que a funcao ja reescreveu entra contado como
        # ativa -- entao o que sobrar fora dela e o que a recifra nao
        # alcancou (nao devia sobrar nada).
        fora_da_ativa += sum(v for chave, v in por_chave.items() if chave != ativa)
    await dispose_engine()
    print(f"blobs fora da chave ativa: {fora_da_ativa}")
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
