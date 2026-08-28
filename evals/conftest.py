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
from mobia.evals.metricas import PISO_DE_TURNOS, PISO_DE_TURNOS_ANOTADOS

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

    Confere os dois pisos, nao so `PISO_DE_TURNOS`: `PISO_DE_TURNOS_ANOTADOS`
    e irmao dele e tinha ficado sem guarda aqui e no fim do runner, so no
    unit test do corpus commitado. Um corpus editado a mao no disco podia ter
    120+ turnos e poucos deles anotados -- passava este pre-voo e so
    `precisao_da_extracao` sofreria, silenciosamente, com uma amostra de
    campo pequena de mais para o piso de 85% significar algo.
    """
    carregadas = carregar(CORPUS)
    turnos = total_de_turnos(carregadas)
    if turnos < PISO_DE_TURNOS:
        pytest.fail(
            f"corpus com {turnos} turnos, piso {PISO_DE_TURNOS}: abortado antes "
            f"da primeira chamada paga, porque a execucao nao teria amostra."
        )
    anotados = sum(1 for conversa in carregadas for turno in conversa.turnos if turno.campos)
    if anotados < PISO_DE_TURNOS_ANOTADOS:
        pytest.fail(
            f"corpus com {anotados} turnos anotados, piso {PISO_DE_TURNOS_ANOTADOS}: "
            f"abortado antes da primeira chamada paga, porque a precisao da extracao "
            f"nao teria amostra."
        )
    return carregadas
