"""Fixtures do eval.

Este diretorio fica fora de `tests/` de proposito: o conftest de la tem
`migrar_banco` e `banco_limpo` como `autouse`, e qualquer arquivo sob `tests/`
passaria a exigir Postgres. O eval nao toca banco -- monta `ContextoMontado`
direto e chama `classificar`.

`testpaths = ["tests"]` no pyproject garante que `pytest` puro nunca colete
este diretorio. Rode de proposito: `pytest evals`.
"""

from pathlib import Path

import pytest

from mobia.evals.corpus import ConversaAnotada, carregar

CORPUS = Path(__file__).resolve().parent / "corpus"


@pytest.fixture(scope="session")
def conversas() -> list[ConversaAnotada]:
    return carregar(CORPUS)
