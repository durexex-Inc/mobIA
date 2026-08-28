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
