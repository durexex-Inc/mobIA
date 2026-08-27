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

from mobia.evals.corpus import ConversaAnotada, carregar, total_de_turnos
from mobia.evals.metricas import PISO_DE_TURNOS

CORPUS = Path(__file__).resolve().parent / "corpus"


@pytest.fixture(scope="session")
def conversas() -> list[ConversaAnotada]:
    """Carrega o corpus e confere o tamanho antes de gastar a primeira chamada.

    O pre-voo e o unico momento em que essa conta sai de graca. Depois dele
    toda descoberta custa dinheiro: um corpus curto medido do jeito antigo
    gastava as ~136 chamadas inteiras para so entao reprovar no piso.

    Nao e o mesmo check de `tests/unit/test_evals_corpus_real.py`, que guarda o
    corpus **commitado** no CI, nem o do fim do runner, que guarda o que
    **sobrou** depois do abandono por infraestrutura. Este guarda o corpus como
    esta no disco agora, na maquina que vai pagar -- o caso que o unit test nao
    ve e que o `pytest evals` local com corpus meio editado produz.
    """
    carregadas = carregar(CORPUS)
    turnos = total_de_turnos(carregadas)
    if turnos < PISO_DE_TURNOS:
        pytest.fail(
            f"corpus com {turnos} turnos, piso {PISO_DE_TURNOS}: abortado antes "
            f"da primeira chamada paga, porque a execucao nao teria amostra."
        )
    return carregadas
