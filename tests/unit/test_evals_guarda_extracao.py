"""Trava a guarda de `_metricas_de` que decide entre medir e `SEM_MECANISMO`.

`_metricas_de` (`evals/test_acuracia_de_intencao.py`) so calcula
`precisao_da_extracao` quando `positivas >= PISO_DE_TURNOS_ANOTADOS` **e**
`negativas >= PISO_DE_TURNOS_NEGATIVOS`; abaixo de qualquer um dos dois pisos
ela cai em `sem_mecanismo`. Essa guarda nunca teve teste proprio, e e
exatamente o ponto onde um assert irmao (`test_acuracia_de_intencao_no_corpus`)
contava positivos e negativos juntos contra o piso de positivos e se
auto-satisfazia -- consertado por leitura, nao por teste. Um "simplificador"
que trocasse a guarda de volta por `len(observadas) >= PISO_DE_TURNOS_ANOTADOS`
passaria despercebido pelos 302 testes que existiam antes deste arquivo.

Segue o mesmo caminho de import que `test_evals_reperguntas.py` ja usa: nada
aqui chama o modelo, e o import do modulo nao dispara chamada nenhuma -- a
chamada paga so acontece dentro de `test_acuracia_de_intencao_no_corpus`.
"""

from evals.test_acuracia_de_intencao import _metricas_de
from mobia.evals.metricas import (
    PISO_DE_TURNOS_ANOTADOS,
    PISO_DE_TURNOS_NEGATIVOS,
    Classificacao,
    ExtracaoObservada,
    Faixa,
)


def _positivo(indice: int) -> ExtracaoObservada:
    return ExtracaoObservada(
        conversa_id="c", indice=indice, esperado={"quartos": 2}, obtido={"quartos": 2}
    )


def _negativo(indice: int) -> ExtracaoObservada:
    return ExtracaoObservada(conversa_id="c", indice=indice, esperado={}, obtido={})


def _faixa_da_extracao(
    resultados: list[Classificacao], observadas: list[ExtracaoObservada]
) -> Faixa:
    metricas = _metricas_de(resultados, observadas)
    extracao = next(m for m in metricas if m.nome == "precisao da extracao")
    return extracao.faixa


def test_positivos_suficientes_e_negativos_de_menos_cai_em_sem_mecanismo() -> None:
    """`positivas` sozinha bastando seria o furo que motivou este arquivo: um
    `len(observadas) >= PISO_DE_TURNOS_ANOTADOS` passaria aqui, porque
    positivos + negativos ja soma acima do piso de positivos."""
    observadas = [_positivo(i) for i in range(PISO_DE_TURNOS_ANOTADOS)]
    observadas += [_negativo(i) for i in range(PISO_DE_TURNOS_NEGATIVOS - 1)]

    assert _faixa_da_extracao([], observadas) is Faixa.SEM_MECANISMO


def test_positivos_de_menos_e_negativos_suficientes_cai_em_sem_mecanismo() -> None:
    """O espelho do caso acima: negativos sozinhos nao sustentam a metrica,
    mesmo quando ja passam do proprio piso."""
    observadas = [_positivo(i) for i in range(PISO_DE_TURNOS_ANOTADOS - 1)]
    observadas += [_negativo(i) for i in range(PISO_DE_TURNOS_NEGATIVOS)]

    assert _faixa_da_extracao([], observadas) is Faixa.SEM_MECANISMO


def test_os_dois_pisos_satisfeitos_mede_a_metrica() -> None:
    """Com os dois pisos batidos a guarda libera `precisao_da_extracao` de
    verdade -- nao fica presa em `SEM_MECANISMO` para sempre."""
    observadas = [_positivo(i) for i in range(PISO_DE_TURNOS_ANOTADOS)]
    observadas += [_negativo(PISO_DE_TURNOS_ANOTADOS + i) for i in range(PISO_DE_TURNOS_NEGATIVOS)]

    assert _faixa_da_extracao([], observadas) is not Faixa.SEM_MECANISMO
