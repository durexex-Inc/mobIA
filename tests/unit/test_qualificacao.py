import pytest

from mobia.domain.agente.schemas import Intencao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.qualificacao import esta_qualificado


def _estado(**campos) -> LeadQualification:
    """Um estado com os quatro obrigatorios preenchidos, menos o que o teste tirar.

    Construir o objeto sem sessao e proposital: a regra e pura e nao deve
    precisar de banco para ser exercitada.
    """
    base = {
        "channel": "whatsapp",
        "conversation_key": "5511999999999",
        "intencao": Intencao.COMPRA.value,
        "faixa_preco_max_centavos": 60_000_000,
        "regiao": "zona sul",
        "urgencia": "ATE_3_MESES",
    }
    return LeadQualification(**{**base, **campos})


def test_quatro_obrigatorios_preenchidos_qualificam():
    assert esta_qualificado(_estado()) is True


def test_estado_inexistente_nao_qualifica():
    """Lead que ainda nao tem linha nenhuma. Nao levanta."""
    assert esta_qualificado(None) is False


@pytest.mark.parametrize(
    "faltando",
    ["intencao", "regiao", "urgencia"],
)
def test_falta_de_obrigatorio_impede(faltando):
    assert esta_qualificado(_estado(**{faltando: None})) is False


def test_faixa_aberta_para_cima_qualifica():
    """RN-05.6: "ate 500 mil" grava max e deixa min nulo. Faixa aberta e faixa
    valida -- exigir os dois extremos prenderia em conversa todo lead que fala
    em teto, que e a forma mais comum de dizer orcamento."""
    obtido = esta_qualificado(
        _estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=50_000_000)
    )
    assert obtido is True


def test_faixa_aberta_para_baixo_qualifica():
    obtido = esta_qualificado(
        _estado(faixa_preco_min_centavos=30_000_000, faixa_preco_max_centavos=None)
    )
    assert obtido is True


def test_sem_nenhum_extremo_de_preco_nao_qualifica():
    obtido = esta_qualificado(_estado(faixa_preco_min_centavos=None, faixa_preco_max_centavos=None))
    assert obtido is False


@pytest.mark.parametrize(
    "intencao",
    [Intencao.COMPRA, Intencao.ALUGUEL, Intencao.INVESTIMENTO],
)
def test_intencoes_qualificaveis(intencao):
    assert esta_qualificado(_estado(intencao=intencao.value)) is True


@pytest.mark.parametrize(
    "intencao",
    [Intencao.VENDER_IMOVEL, Intencao.SUPORTE_CONTRATO],
)
def test_intencao_de_handoff_nao_qualifica_mesmo_completa(intencao):
    """RN-03.4: VENDER_IMOVEL e SUPORTE_CONTRATO vao direto para handoff, nao
    para qualificacao. Os quatro campos podem estar preenchidos numa conversa
    dessas, e a RN-05.3 lida sozinha diria que qualifica. E o ponto onde as
    duas regras do SRS divergem, e a D2 escolheu esta leitura."""
    assert esta_qualificado(_estado(intencao=intencao.value)) is False


@pytest.mark.parametrize(
    "intencao",
    [Intencao.INDEFINIDA, Intencao.FORA_DE_ESCOPO],
)
def test_ausencia_de_intencao_nao_conta_como_intencao(intencao):
    """Depois do primeiro turno `intencao` nunca e nula -- o classificador
    sempre devolve um dos sete valores. Entao "intencao preenchida" nao pode
    ser "nao e nulo", ou a coluna estaria sempre preenchida."""
    assert esta_qualificado(_estado(intencao=intencao.value)) is False


@pytest.mark.parametrize(
    "campo",
    ["intencao", "faixa_preco", "regiao", "urgencia"],
)
def test_campo_recusado_nao_conta(campo):
    assert esta_qualificado(_estado(), recusados=frozenset({campo})) is False


def test_recusado_vence_o_valor_gravado():
    """D4, e a borda estranha declarada no desenho: o lead disse 500 mil e
    depois recusou falar de orcamento. O valor continua na coluna e o lead
    deixa de ser qualificado. E a regra da card, nao invencao do codigo."""
    obtido = esta_qualificado(
        _estado(faixa_preco_max_centavos=50_000_000), recusados=frozenset({"faixa_preco"})
    )
    assert obtido is False


def test_recusa_de_campo_desejavel_nao_atrapalha():
    """Recusar `vagas` nao e recusar obrigatorio nenhum."""
    assert esta_qualificado(_estado(), recusados=frozenset({"vagas"})) is True
