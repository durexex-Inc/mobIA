"""A chamada do subagente investidor. TEC-153, RN-07.1, D1 e D2."""

from decimal import Decimal

from mobia.domain.agente.classificador import (
    MAX_RETORNO_ESPERADO_PCT,
    SCHEMA_DA_RESPOSTA,
    SCHEMA_DO_INVESTIDOR,
    SISTEMA_DO_INVESTIDOR,
    _extracao_do_investidor,
    _retorno_pct,
)
from mobia.domain.agente.investidor import (
    ExtracaoDoInvestidor,
    Horizonte,
    RetornoEsperadoTipo,
    ToleranciaReforma,
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


def test_o_objeto_ausente_nao_derruba_o_turno() -> None:
    """Mesmo contrato de `extrair`: qualificacao perdida e barata perto de uma
    resposta paga e nao entregue ao lead."""
    assert _extracao_do_investidor(None) == ExtracaoDoInvestidor()
    assert _extracao_do_investidor("investidor") == ExtracaoDoInvestidor()
    assert _extracao_do_investidor({}) == ExtracaoDoInvestidor()


def test_os_seis_campos_bem_formados_atravessam() -> None:
    extraida = _extracao_do_investidor(
        {
            "ticket_expressao": "  uns 800 mil  ",
            "retorno_esperado_pct": 8.5,
            "retorno_esperado_tipo": "ALUGUEL",
            "horizonte": "LONGO",
            "tolerancia_reforma": "LEVE",
            "ja_investe_em_imoveis": True,
        }
    )
    # Fica como o lead falou: quem normaliza e `ticket_de`, na gravacao, para
    # que a conversao seja a mesma da trilha padrao.
    assert extraida.ticket_expressao == "uns 800 mil"
    assert extraida.retorno_esperado_pct == Decimal("8.50")
    assert extraida.retorno_esperado_tipo is RetornoEsperadoTipo.ALUGUEL
    assert extraida.horizonte is Horizonte.LONGO
    assert extraida.tolerancia_reforma is ToleranciaReforma.LEVE
    assert extraida.ja_investe_em_imoveis is True


def test_valor_de_enum_que_o_codigo_nao_conhece_vira_none() -> None:
    """O schema estrito deveria impedir, mas um campo so nao pode custar os
    outros cinco do mesmo turno."""
    extraida = _extracao_do_investidor({"horizonte": "ETERNO", "tolerancia_reforma": 7})
    assert extraida.horizonte is None
    assert extraida.tolerancia_reforma is None


def test_o_ticket_vazio_e_turno_comum_e_nao_recusa() -> None:
    assert _extracao_do_investidor({"ticket_expressao": "   "}).ticket_expressao is None
    assert _extracao_do_investidor({"ticket_expressao": 800000}).ticket_expressao is None


def test_o_percentual_e_quantizado_na_escala_da_coluna() -> None:
    """`numeric(4,2)`: o valor que este turno usa tem de ser o que fica
    gravado, e `ROUND_HALF_UP` e o modo do Postgres, nao o do Decimal."""
    assert _retorno_pct(8) == Decimal("8.00")
    assert _retorno_pct(8.005) == Decimal("8.01")
    # A borda pertence a faixa, e chega como o `float` que `json.loads`
    # produz -- nunca como `Decimal`, que e so a forma da constante.
    assert _retorno_pct(99.99) == MAX_RETORNO_ESPERADO_PCT
    # E logo acima dela o valor cai fora ANTES de quantizar, que e o que
    # importa: 99.995 arredondaria para 100.00 e estouraria o `numeric(4,2)`
    # no commit -- a guarda de faixa existe para isso, e nao para o numero
    # redondo.
    assert _retorno_pct(99.995) is None


def test_o_percentual_fora_do_que_a_coluna_aceita_e_descartado() -> None:
    """Acima de 99,99 seria `DataError` no commit; negativo e prejuizo
    esperado, que nao e expectativa de retorno. E `True` e `int` em Python."""
    assert _retorno_pct(100) is None
    assert _retorno_pct(-1) is None
    assert _retorno_pct(True) is None
    assert _retorno_pct("8%") is None
    # Os literais nao-padrao que `json.loads` aceita sem reclamar: toda
    # comparacao com NaN e falsa e os infinitos caem fora da faixa, entao
    # nenhum deles chega ao `Decimal(str(...))`.
    assert _retorno_pct(float("nan")) is None
    assert _retorno_pct(float("inf")) is None
    # Inteiro de centenas de digitos: rejeitado sem nenhuma conversao para
    # float, que levantaria OverflowError fora do contrato deste modulo.
    assert _retorno_pct(10**320) is None
