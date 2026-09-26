from mobia.domain.moderacao.port import (
    TEXTO_DA_RECUSA_DE_ENTRADA,
    TEXTO_NEUTRO_DE_SAIDA,
    Direcao,
    Veredito,
)


def test_as_duas_direcoes_existem_e_sao_distintas() -> None:
    """A direcao nao e decoracao: o prompt difere entre julgar a fala de um
    estranho e julgar o que a empresa vai dizer em nome proprio.
    """
    assert Direcao.ENTRADA != Direcao.SAIDA
    assert {d.value for d in Direcao} == {"ENTRADA", "SAIDA"}


def test_veredito_e_imutavel() -> None:
    """Frozen de proposito: o veredito atravessa o turno e nao pode ser
    reescrito no caminho por quem nao gostou dele.
    """
    import dataclasses

    import pytest

    v = Veredito(bloqueado=True, motivo="teste")
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.motivo = "outro"  # type: ignore[misc]


def test_o_texto_da_recusa_nao_explica_o_criterio() -> None:
    """Explicar o criterio ensina a contorna-lo. A recusa e curta, neutra, e
    nao acusa o lead -- falso positivo em moderacao e comum, e o lead legitimo
    que caiu nele nao pode ser tratado como infrator.
    """
    baixo = TEXTO_DA_RECUSA_DE_ENTRADA.lower()
    for proibido in ("impropri", "ofensiv", "bloque", "viola", "proibid", "regra"):
        assert proibido not in baixo
    assert 0 < len(TEXTO_DA_RECUSA_DE_ENTRADA) <= 200


def test_a_recusa_nomeia_o_criterio_legitimo() -> None:
    """O segundo passo do criterio de aceite da TEC-142: explicar que a busca e
    por criterio do imovel. Dizer o que E aceito, em vez do que foi recusado,
    cumpre a card sem quebrar as duas regras do texto -- nao explica o criterio
    de bloqueio e nao acusa o lead.
    """
    baixo = TEXTO_DA_RECUSA_DE_ENTRADA.lower()
    assert "imóvel" in baixo
    for criterio in ("região", "preço", "quartos"):
        assert criterio in baixo


def test_o_texto_neutro_de_saida_nao_finge_ser_resposta() -> None:
    """Ele nao pode parecer que respondeu a pergunta do lead. O lead precisa
    perceber que algo nao saiu, senao espera por uma resposta que nao vem.
    """
    assert 0 < len(TEXTO_NEUTRO_DE_SAIDA) <= 200
    assert TEXTO_NEUTRO_DE_SAIDA != TEXTO_DA_RECUSA_DE_ENTRADA


def test_o_modelo_da_moderacao_e_campo_proprio() -> None:
    """Amarrar moderacao ao `modelo_agente` faria uma troca de modelo mudar em
    silencio o custo e a latencia da moderacao de todo turno. E `config.py`
    esta fora do filtro do gate da TEC-210, entao a troca passa sem re-medir.
    """
    from mobia.app.config import get_settings

    settings = get_settings()
    assert settings.modelo_moderacao
    assert hasattr(settings, "modelo_agente")


def test_o_vocabulario_difere_por_direcao() -> None:
    """As duas listas nao sao a mesma porque os dois prompts nunca foram o
    mesmo: ofensa ao lead so a saida bloqueia, incitacao so a entrada nomeia.
    """
    from mobia.domain.moderacao.port import CATEGORIAS_POR_DIRECAO

    entrada = CATEGORIAS_POR_DIRECAO[Direcao.ENTRADA]
    saida = CATEGORIAS_POR_DIRECAO[Direcao.SAIDA]

    # `INJECAO` e da TEC-204 e nao bloqueia -- ver
    # `test_injecao_e_categoria_de_entrada_e_nao_bloqueia`.
    assert entrada == frozenset({"DISCRIMINACAO", "AMEACA", "ASSEDIO", "VIOLENCIA", "INJECAO"})
    assert saida == frozenset(
        {"DISCRIMINACAO", "AMEACA", "ASSEDIO", "OFENSA", "ACONSELHAMENTO", "NEGOCIACAO"}
    )
    assert "OFENSA" not in entrada
    assert "VIOLENCIA" not in saida


def test_negociacao_e_categoria_da_saida() -> None:
    """A TEC-141 mandou a saida bloquear negociacao de valor. Sem a palavra no
    vocabulario o modelo responderia fora do protocolo justo no caso que
    aquela card criou.
    """
    from mobia.domain.moderacao.port import CATEGORIAS_POR_DIRECAO

    assert "NEGOCIACAO" in CATEGORIAS_POR_DIRECAO[Direcao.SAIDA]


def test_outro_nao_pertence_a_nenhum_vocabulario() -> None:
    """`OUTRO` e fracasso de protocolo, nao categoria do dominio: o modelo
    nunca deve escolhe-lo, so cair nele. Ofertar a palavra convidaria o
    modelo a usar a saida facil em vez de decidir.
    """
    from mobia.domain.moderacao.port import CATEGORIA_OUTRO, CATEGORIAS_POR_DIRECAO

    for categorias in CATEGORIAS_POR_DIRECAO.values():
        assert CATEGORIA_OUTRO not in categorias


def test_veredito_liberado_nao_tem_categoria() -> None:
    """Nao ha categoria de liberacao a inventar: `None` e o veredito liberado."""
    assert Veredito(bloqueado=False, motivo="x").categoria is None


def test_veredito_continua_imutavel_com_a_categoria() -> None:
    import dataclasses

    import pytest

    v = Veredito(bloqueado=True, motivo="x", categoria="DISCRIMINACAO")
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.categoria = "AMEACA"  # type: ignore[misc]


def test_injecao_e_categoria_de_entrada_e_nao_bloqueia() -> None:
    """TEC-204, D3. A deteccao e registro, nao defesa: o conjunto do que
    bloqueia e explicito, e a categoria nova nao depende de um `if` no turno."""
    from mobia.domain.moderacao.port import (
        CATEGORIA_INJECAO,
        CATEGORIAS_POR_DIRECAO,
        CATEGORIAS_QUE_BLOQUEIAM,
        Direcao,
    )

    assert CATEGORIA_INJECAO in CATEGORIAS_POR_DIRECAO[Direcao.ENTRADA]
    assert CATEGORIA_INJECAO not in CATEGORIAS_POR_DIRECAO[Direcao.SAIDA]
    assert CATEGORIA_INJECAO not in CATEGORIAS_QUE_BLOQUEIAM


def test_o_que_bloqueia_e_todo_o_vocabulario_menos_a_injecao() -> None:
    """O literal e para ler; este teste impede que ele diverja do vocabulario."""
    from mobia.domain.moderacao.port import (
        CATEGORIA_INJECAO,
        CATEGORIAS_POR_DIRECAO,
        CATEGORIAS_QUE_BLOQUEIAM,
    )

    todas = frozenset().union(*CATEGORIAS_POR_DIRECAO.values())
    assert CATEGORIAS_QUE_BLOQUEIAM == todas - {CATEGORIA_INJECAO}


def test_veredito_sem_injecao_por_padrao() -> None:
    from mobia.domain.moderacao.port import Veredito

    assert Veredito(bloqueado=False, motivo="x").injecao is False
