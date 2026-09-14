"""A chamada do subagente investidor. TEC-153, RN-07.1, D1 e D2."""

from mobia.domain.agente.classificador import (
    SCHEMA_DA_RESPOSTA,
    SCHEMA_DO_INVESTIDOR,
    SISTEMA_DO_INVESTIDOR,
)


def test_o_objeto_do_investidor_nao_entra_no_schema_principal() -> None:
    """E disto que depende o custo zero para quem nao e investidor: o schema
    compilado e uma das quatro parcelas do orcamento de prompt, e seis campos
    que a maioria dos leads nunca preenche nao podem custar tokens a todos.
    TEC-153, D2.

    A asserta e sobre o OBJETO `investidor`, e nao sobre as chaves em comum:
    o schema do investidor e o MESMO envelope com um objeto a mais, entao
    `intencao`, `resposta` e `extracao` aparecem nos dois de proposito.
    """
    assert "investidor" not in SCHEMA_DA_RESPOSTA["properties"]
    assert "investidor" in SCHEMA_DO_INVESTIDOR["properties"]


def test_o_schema_do_investidor_carrega_o_envelope_inteiro() -> None:
    """Um investidor tambem diz regiao, tipo e faixa de preco, e o turno dele
    continua precisando classificar intencao. Trocar a extracao inteira pelo
    objeto do investidor perderia tudo isso."""
    for campo in ("intencao", "confianca", "resposta", "extracao", "perguntou", "recusou"):
        assert campo in SCHEMA_DO_INVESTIDOR["properties"], campo


def test_os_dois_schemas_sao_objetos_distintos() -> None:
    """Montar um a partir do outro por referencia faria uma mutacao futura no
    do investidor vazar para o principal -- e o orcamento so e protegido
    porque eles nao se tocam."""
    assert SCHEMA_DO_INVESTIDOR is not SCHEMA_DA_RESPOSTA
    assert SCHEMA_DO_INVESTIDOR["properties"] is not SCHEMA_DA_RESPOSTA["properties"]


def test_o_prompt_do_investidor_e_diferente_do_principal() -> None:
    from mobia.domain.agente.classificador import SISTEMA_DO_AGENTE

    assert SISTEMA_DO_INVESTIDOR != SISTEMA_DO_AGENTE


def test_o_prompt_do_investidor_nao_pede_quartos_nem_vagas() -> None:
    """Cenario 1 do Gherkin: "o agente nao pergunta sobre numero de quartos"."""
    baixo = SISTEMA_DO_INVESTIDOR.lower()
    assert "quarto" not in baixo
    assert "vaga" not in baixo
