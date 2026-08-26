from mobia.domain.agente.classificador import SCHEMA_DA_RESPOSTA
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


def test_schema_deriva_do_enum() -> None:
    """O enum e a fonte da verdade: acrescentar intencao muda o schema junto.

    Duas listas mantidas a mao divergem, e a divergencia so aparece quando o
    modelo devolve um valor que o codigo nao sabe converter.
    """
    valores = SCHEMA_DA_RESPOSTA["properties"]["intencao"]["enum"]
    assert set(valores) == {membro.value for membro in Intencao}


def test_schema_e_estrito() -> None:
    """Sem additionalProperties: false o modelo pode inventar campo."""
    assert SCHEMA_DA_RESPOSTA["additionalProperties"] is False
    assert set(SCHEMA_DA_RESPOSTA["required"]) == {"intencao", "confianca", "resposta"}


def test_confianca_e_limitada_no_schema() -> None:
    confianca = SCHEMA_DA_RESPOSTA["properties"]["confianca"]
    assert confianca["minimum"] == 0
    assert confianca["maximum"] == 1
