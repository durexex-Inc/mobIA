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
    RespostaObservada,
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
    # `respostas=[]` de proposito: este arquivo trava a guarda da extracao, e a
    # aderencia ao tom (TEC-140) nao participa dela. Lista vazia e o caso real
    # de uma execucao que morreu antes de gerar resposta -- ela cai em
    # `sem_mecanismo`, que e o que `test_sem_resposta_a_aderencia_cai_em_sem_mecanismo`
    # abaixo trava.
    metricas = _metricas_de(resultados, observadas, [])
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


def test_sem_resposta_a_aderencia_cai_em_sem_mecanismo() -> None:
    """A metrica nova tem a mesma guarda das outras, e pelo mesmo motivo.

    `faixa_de` recusa total zero -- "nada medido nao e sucesso" --, entao
    `aderencia_ao_tom([])` levantaria. Levantar **aqui** apagaria o relatorio,
    que e o unico artefato de uma execucao paga que morreu na rede. O
    raciocinio e o mesmo que ja protege a acuracia de intencao em
    `_metricas_de`.
    """
    metricas = _metricas_de([], [], [])
    tom = next(m for m in metricas if m.nome == "aderencia ao tom")

    assert tom.faixa is Faixa.SEM_MECANISMO
    assert "nenhuma resposta" in tom.detalhe


def test_com_resposta_a_aderencia_e_medida() -> None:
    """Com amostra ela sai do slot e vira numero -- nao fica presa em
    `SEM_MECANISMO` para sempre, que era o estado ate a TEC-140."""
    metricas = _metricas_de([], [], [RespostaObservada(conversa_id="c", indice=0, texto="ok")])
    tom = next(m for m in metricas if m.nome == "aderencia ao tom")

    assert tom.faixa is not Faixa.SEM_MECANISMO
    assert (tom.acertos, tom.total) == (1, 1)
