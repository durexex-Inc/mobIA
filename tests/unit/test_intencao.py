from mobia.domain.agente.schemas import Intencao


def test_as_sete_intencoes_da_regra_de_negocio() -> None:
    """RN-03.1 lista exatamente estas. Nem uma a mais, nem a menos.

    O schema estrito da chamada ao modelo e gerado a partir deste enum, entao
    acrescentar um valor aqui muda o que o modelo pode devolver.
    """
    assert {membro.value for membro in Intencao} == {
        "COMPRA",
        "ALUGUEL",
        "INVESTIMENTO",
        "VENDER_IMOVEL",
        "SUPORTE_CONTRATO",
        "INDEFINIDA",
        "FORA_DE_ESCOPO",
    }


def test_intencao_e_string_no_banco() -> None:
    """StrEnum: a coluna guarda o valor, nao o repr do membro."""
    assert f"{Intencao.INVESTIMENTO}" == "INVESTIMENTO"
