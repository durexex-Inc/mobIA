"""A regra da RN-05.3, e a regra de acumulacao que a alimenta.

As duas moram no mesmo arquivo porque o defeito que a revisao final achou nao
estava em nenhuma das duas isoladamente: `esta_qualificado` so ve a linha
atual, e o que decide o que a linha carrega e `campos_a_gravar`. Testar as
duas separadas foi exatamente o que deixou passar `INDEFINIDA` apagando uma
intencao boa.
"""

import pytest

from mobia.domain.agente.schemas import Extracao, Intencao, Urgencia
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import _texto_do_estado
from mobia.domain.context.qualificacao import CAMPOS_OBRIGATORIOS, esta_qualificado
from mobia.domain.context.repositorio import _MARCA_DO_ORCAMENTO, _NOME_DA_MARCA, campos_a_gravar


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
        "urgencia": Urgencia.ATE_3_MESES.value,
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


def test_recusa_do_orcamento_vale_sob_qualquer_nome_que_o_repo_use():
    """Pina o MECANISMO, e nao a instancia: os nomes saem das fontes de
    verdade, nao de uma lista escrita a mao aqui.

    `CAMPOS_OBRIGATORIOS` chama o orcamento de `faixa_preco`, que nao e nome
    de coluna, nem de campo de `Extracao`, nem a chave que o prompt
    renderiza, nem a marca que `campos_a_marcar` grava. A TEC-148, que e quem
    vai preencher `recusados`, so tem o vocabulario da marca a mao -- e
    `faixa_preco_max` nao esta em `CAMPOS_OBRIGATORIOS`. Sem a traducao, o
    laco nunca ve a recusa, e um lead que se recusou a falar de orcamento
    qualifica assim mesmo sobre um preco velho, com teste verde nas duas
    cards. Foi assim que a TEC-146 queimou uma card inteira.
    """
    colunas = set(LeadQualification.__table__.columns.keys())
    # As chaves que so existem no prompt sao exatamente `faixa_preco_min` e
    # `faixa_preco_max`: todas as outras linhas de `_texto_do_estado` saem de
    # uma coluna com o mesmo nome. Derivar por subtracao e o que impede este
    # teste de virar uma copia da lista que ele deveria estar conferindo.
    so_do_prompt = {
        linha.split(":", 1)[0] for linha in _texto_do_estado(_estado()).splitlines()
    } - colunas
    assert so_do_prompt, "nenhuma chave so-do-prompt: a derivacao deixou de valer"

    nomes = {_MARCA_DO_ORCAMENTO, *_NOME_DA_MARCA, *_NOME_DA_MARCA.values(), *so_do_prompt}
    assert "faixa_preco_max" in nomes, "o vocabulario da marca sumiu da derivacao"

    for nome in nomes:
        assert esta_qualificado(_estado(), recusados=frozenset({nome})) is False, (
            f"recusa de orcamento sob o nome {nome!r} foi ignorada em silencio"
        )


def test_o_nome_logico_do_orcamento_nao_e_coluna_nem_campo_de_extracao():
    """A razao de `_canonico` existir, travada: os dois vocabularios de fato
    divergem, entao a traducao nao e defensiva decorativa."""
    colunas = set(LeadQualification.__table__.columns.keys())
    assert "faixa_preco" in CAMPOS_OBRIGATORIOS
    assert "faixa_preco" not in colunas
    assert "faixa_preco" != _MARCA_DO_ORCAMENTO


def test_indefinida_nao_sobrescreve_a_intencao_gravada():
    """C1, na funcao. `INDEFINIDA` e "ainda nao da para saber", e o
    classificador pode devolve-la em qualquer turno -- um "obrigado" basta.
    Deixando-a entrar no dict, ela apaga o COMPRA que ja estava na coluna, e
    todo o resto desta tabela honra "None nao apaga"."""
    assert "intencao" not in campos_a_gravar(Intencao.INDEFINIDA, Extracao())
    assert campos_a_gravar(Intencao.INDEFINIDA, Extracao()) == {}


def test_indefinida_ainda_grava_os_campos_de_extracao():
    """So a chave `intencao` sai. O lead que diz "zona sul, ate 600 mil" sem
    deixar claro se compra ou aluga informou regiao e preco, e isso e fato
    sobre a fala dele -- nao depende de sabermos a intencao."""
    campos = campos_a_gravar(
        Intencao.INDEFINIDA, Extracao(regiao="zona sul", faixa_preco_max_centavos=60_000_000)
    )
    assert campos == {"regiao": "zona sul", "faixa_preco_max_centavos": 60_000_000}


def test_intencao_boa_sobrevive_a_um_turno_indefinido():
    """A sequencia inteira da C1, sem banco: o `dict.update` e a mesma
    acumulacao que o `ON CONFLICT DO UPDATE` faz, e que o runner do eval faz.

    Antes da correcao, o turno 2 zerava a qualificacao e o turno 3 disparava
    `lead.qualificado` de novo -- a taxa da RN-17.1 contando travessias em vez
    de leads.
    """
    acumulado: dict[str, object] = {"channel": "whatsapp", "conversation_key": "5511999999999"}

    acumulado.update(
        campos_a_gravar(
            Intencao.COMPRA,
            Extracao(
                faixa_preco_max_centavos=60_000_000,
                regiao="zona sul",
                urgencia=Urgencia.ATE_3_MESES,
            ),
        )
    )
    assert esta_qualificado(LeadQualification(**acumulado)) is True

    # "obrigado" -- o classificador nao consegue dizer nada sobre esta fala.
    acumulado.update(campos_a_gravar(Intencao.INDEFINIDA, Extracao()))
    assert esta_qualificado(LeadQualification(**acumulado)) is True, (
        "um turno ambiguo desqualificou um lead que ja estava qualificado"
    )

    # O lead volta ao assunto. Ele nunca deixou de estar qualificado, entao
    # nao ha travessia nova aqui.
    acumulado.update(campos_a_gravar(Intencao.COMPRA, Extracao(vagas=1)))
    assert esta_qualificado(LeadQualification(**acumulado)) is True
