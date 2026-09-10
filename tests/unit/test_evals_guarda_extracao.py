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

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from evals.test_acuracia_de_intencao import _metricas_de, _rodar_conversa
from mobia.domain.agente.citacao import Divergencia
from mobia.domain.agente.schemas import Extracao, Intencao, RespostaDoAgente
from mobia.evals.corpus import ConversaAnotada, TurnoAnotado
from mobia.evals.metricas import (
    PISO_DE_TURNOS_ANOTADOS,
    PISO_DE_TURNOS_NEGATIVOS,
    Classificacao,
    ExtracaoObservada,
    Faixa,
    InvencaoObservada,
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
    metricas = _metricas_de(resultados, observadas, [], [])
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
    metricas = _metricas_de([], [], [], [])
    tom = next(m for m in metricas if m.nome == "aderencia ao tom")

    assert tom.faixa is Faixa.SEM_MECANISMO
    assert "nenhuma resposta" in tom.detalhe


def test_com_resposta_a_aderencia_e_medida() -> None:
    """Com amostra ela sai do slot e vira numero -- nao fica presa em
    `SEM_MECANISMO` para sempre, que era o estado ate a TEC-140."""
    metricas = _metricas_de([], [], [RespostaObservada(conversa_id="c", indice=0, texto="ok")], [])
    tom = next(m for m in metricas if m.nome == "aderencia ao tom")

    assert tom.faixa is not Faixa.SEM_MECANISMO
    assert (tom.acertos, tom.total) == (1, 1)


def test_sem_resposta_a_taxa_de_alucinacao_cai_em_sem_mecanismo() -> None:
    """TEC-269: a metrica nova tem a mesma guarda de amostra que a aderencia.

    O comportamento da propria `taxa_de_alucinacao` ja esta travado em
    `test_evals_metricas.py::test_sem_amostra_volta_para_sem_mecanismo`; este
    teste trava so que o slot existe em `_metricas_de` e cai em
    `sem_mecanismo` sem amostra, do mesmo jeito que ja acontecia para
    `aderencia_ao_tom`. Com `invencoes=[]` e `respostas=[]` ele NAO distingue
    `_metricas_de` chamando `taxa_de_alucinacao(invencoes, respostas)` de uma
    chamada hardcoded `taxa_de_alucinacao([], respostas)` -- essa distincao
    fica para o teste positivo mais abaixo, que passa uma invencao de
    verdade.
    """
    metricas = _metricas_de([], [], [], [])
    taxa = next(m for m in metricas if m.nome == "taxa de alucinacao (cifra e codigo)")

    assert taxa.faixa is Faixa.SEM_MECANISMO
    assert "nenhuma resposta" in taxa.detalhe


def test_com_invencao_a_taxa_de_alucinacao_e_medida() -> None:
    """O positivo do teste acima: com amostra e uma invencao de verdade,
    `_metricas_de` devolve a taxa MEDIDA, e nao `SEM_MECANISMO`.

    Ate aqui so o caminho vazio (teste acima) estava travado, e ele nao
    distingue `_metricas_de` repassando `invencoes` de uma chamada hardcoded
    com lista vazia -- as duas dao `SEM_MECANISMO` do mesmo jeito quando
    `respostas` tambem esta vazia. Este teste fecha essa lacuna: verificado
    contra a variante quebrada (trocar `taxa_de_alucinacao(invencoes,
    respostas)` por `taxa_de_alucinacao([], respostas)` em `_metricas_de`),
    ele vai a vermelho -- ver o relatorio final da TEC-269 para o registro.
    """
    resposta = RespostaObservada(conversa_id="c", indice=0, texto="Tenho um otimo por R$ 900 mil.")
    invencao = InvencaoObservada(
        conversa_id="c",
        indice=0,
        divergencias=(Divergencia(tipo="preco", citado="R$ 900.000"),),
    )
    metricas = _metricas_de([], [], [resposta], [invencao])
    taxa = next(m for m in metricas if m.nome == "taxa de alucinacao (cifra e codigo)")

    assert taxa.faixa is not Faixa.SEM_MECANISMO
    assert (taxa.acertos, taxa.total) == (0, 1)


def _resposta_do_agente(
    texto: str,
    *,
    intencao: Intencao = Intencao.COMPRA,
    extracao: Extracao | None = None,
) -> RespostaDoAgente:
    """Uma `RespostaDoAgente` minima, para alimentar o classificador encenado
    abaixo sem pagar chamada nenhuma."""
    return RespostaDoAgente(
        intencao=intencao,
        confianca=Decimal("0.9"),
        resposta=texto,
        modelo="stub",
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        extracao=extracao if extracao is not None else Extracao(),
    )


class _ClassificadorEncenado:
    """Devolve respostas canonicas em sequencia, sem rede nem banco.

    Contrato reduzido ao que `_rodar_conversa` chama: `classificar(contexto)`
    sem `porta=` -- nao implementa `desambiguar` porque `_rodar_conversa`
    nunca o chama. TEC-269, F4 da revisao final: prova que a fiacao do laco
    (D3) funciona sem gastar uma chamada real. `_rodar_conversa` e importavel
    de `tests/unit/` pelo mesmo caminho que este arquivo ja usa para
    `_metricas_de`.
    """

    def __init__(self, respostas: Sequence[RespostaDoAgente]) -> None:
        self._respostas = list(respostas)

    async def classificar(self, contexto: Any) -> RespostaDoAgente:
        return self._respostas.pop(0)


async def test_eco_do_orcamento_extraido_no_mesmo_turno_nao_e_invencao() -> None:
    """D3: a faixa que a guarda ve e a de DEPOIS de
    `estado_acumulado.update(...)`, porque em producao a guarda le a faixa
    depois de `gravar_estado` -- ela inclui o que o turno corrente acabou de
    extrair. Aqui o lead declara o orcamento, o modelo EXTRAI o mesmo valor
    neste turno, e o agente ecoa o numero na prosa: isso nao pode contar como
    invencao.

    Este e o teste que fica VERMELHO se alguem mover o bloco de coleta de
    `invencoes` para ANTES de `estado_acumulado.update(...)` em
    `_rodar_conversa` -- a regressao contra D3 que a revisao final apontou.
    Verificado: mover o bloco (cortar e colar as linhas de
    `invencao_do_turno(...)` ate `invencoes.append(invencao)` para logo apos
    `conhecidos_antes = _campos_conhecidos(estado_acumulado)`, antes de
    `contexto = contexto_do_historico(...)` -- ou seja, antes de `resposta =
    await classificador.classificar(contexto)` sequer existir) nao faz este
    teste falhar numa assercao: faz `_rodar_conversa` levantar
    `UnboundLocalError: cannot access local variable 'resposta' where it is
    not associated with a value`, porque o bloco movido le `resposta.resposta`
    e `resposta.candidatos` antes de `resposta` ser atribuida. Revertido
    (`git checkout -- evals/test_acuracia_de_intencao.py`), a suite deste
    arquivo volta a passar (9 testes).
    """
    conversa = ConversaAnotada(
        id="c1",
        descricao="lead declara orcamento e o agente ecoa no mesmo turno",
        turnos=[
            TurnoAnotado(
                lead="Posso pagar ate 600 mil.",
                intencao=Intencao.COMPRA,
                campos={"faixa_preco_max_centavos": 60_000_000},
            )
        ],
    )
    resposta = _resposta_do_agente(
        "Entendi, vou procurar ate R$ 600 mil.",
        extracao=Extracao(faixa_preco_max_centavos=60_000_000),
    )
    classificador = _ClassificadorEncenado([resposta])

    (
        _resultados,
        _observadas,
        _reperguntados,
        _respostas,
        _perguntas,
        invencoes,
        _estado,
    ) = await _rodar_conversa(classificador, conversa)

    assert invencoes == []


async def test_cifra_sem_orcamento_extraido_vira_invencao() -> None:
    """O complemento do teste acima: sem faixa extraida (`Extracao()` vazia),
    so a citacao sobra, e o turno e invencao de verdade -- o caso RT-01 puro
    que D1 do desenho descreve.

    Fica VERMELHO se `invencoes.append(invencao)` for apagado do laco de
    `_rodar_conversa`. Verificado: comentar essa linha faz este teste falhar
    com `assert 0 == 1`; revertido, ele volta a passar.
    """
    conversa = ConversaAnotada(
        id="c1",
        descricao="agente cita cifra sem o lead ter declarado orcamento",
        turnos=[
            TurnoAnotado(lead="Quero comprar um apartamento.", intencao=Intencao.COMPRA, campos={})
        ],
    )
    resposta = _resposta_do_agente("Tenho um otimo por R$ 900 mil.")
    classificador = _ClassificadorEncenado([resposta])

    (
        _resultados,
        _observadas,
        _reperguntados,
        _respostas,
        _perguntas,
        invencoes,
        _estado,
    ) = await _rodar_conversa(classificador, conversa)

    assert len(invencoes) == 1
    assert invencoes[0].divergencias[0].tipo == "preco"
