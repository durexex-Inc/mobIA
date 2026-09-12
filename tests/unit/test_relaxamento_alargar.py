"""As formas puras do relaxamento da RN-09.3.

TEC-160. Basename distinto de tudo em `tests/integration/`.
"""

from mobia.domain.catalogo.enums import EstadoDoRelaxamento, Operacao
from mobia.domain.catalogo.relaxamento import alargar, e_relaxavel
from mobia.domain.catalogo.schemas import FiltroDeBusca, ResultadoDaBusca


def test_o_filtro_nasce_nao_relaxado() -> None:
    """D2: o campo existe e o default e o passe duro."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA)

    assert filtro.relaxado is False


def test_o_resultado_nasce_sem_relaxamento() -> None:
    """D6: `buscar` nunca afirma relaxamento -- ela e um passe."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxamento is EstadoDoRelaxamento.NAO_HOUVE


def test_os_tres_estados_sao_distintos() -> None:
    """Um booleano colapsaria os dois ultimos, e a regra 4 da card precisa
    dos tres separados: "nao relaxei" e "relaxei e nao achei" pedem mensagens
    diferentes ao lead."""
    assert len(set(EstadoDoRelaxamento)) == 3


def test_o_resultado_diz_quais_dimensoes_alargou() -> None:
    """D11. O aviso precisa saber EM QUE ampliou, e o estado nao carrega isso:
    `APLICADO` vale tanto para "so preco" quanto para "preco e bairro"."""
    resultado = ResultadoDaBusca(candidatos=(), total_candidatos=0, consulta_vetorizada=False)

    assert resultado.relaxou_preco is False
    assert resultado.relaxou_bairro is False


def test_alargar_marca_o_filtro_e_une_as_regioes() -> None:
    """D8 e a leitura do cenario 4 da card: regioes UNIAO adjacentes.

    "Apenas bairros marcados como adjacentes entram na busca" limita de ONDE
    vem os novos, e nao quem sai. O bairro pedido continua dentro: o passe 1
    nao achou nada nele sob o filtro original, mas com o preco relaxado pode
    haver ali um imovel elegivel, e descarta-lo seria devolver o vizinho e
    esconder o bairro que o lead pediu.
    """
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("trindade",))

    alargado = alargar(filtro, ("centro", "agronomica", "itacorubi"))

    assert alargado.relaxado is True
    assert set(alargado.regioes) == {"trindade", "centro", "agronomica", "itacorubi"}


def test_alargar_preserva_o_teto_original() -> None:
    """D2. A folga e do `WHERE`, dentro de `buscar`; o campo nao se mexe aqui.

    Se `alargar` escrevesse `preco_max_centavos = teto * 1,10`, a ancora da
    ordenacao viajaria junto e a promessa da emenda E-01 da RN-09.6 morreria.
    """
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=40000000)

    alargado = alargar(filtro, ())

    assert alargado.preco_max_centavos == 40000000


def test_alargar_sem_adjacentes_mantem_as_regioes() -> None:
    """Bairro sem linha na tabela nao e erro -- e lista vazia (D13)."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("campeche",))

    alargado = alargar(filtro, ())

    assert alargado.regioes == ("campeche",)


def test_alargar_nao_duplica_regiao_que_ja_estava() -> None:
    """Duplicata viraria `IN` com o mesmo valor duas vezes: ruido no plano."""
    filtro = FiltroDeBusca(operacao=Operacao.VENDA, regioes=("centro",))

    alargado = alargar(filtro, ("centro", "trindade"))

    assert sorted(alargado.regioes) == ["centro", "trindade"]


def test_sem_teto_e_sem_regiao_nada_e_relaxavel() -> None:
    """D5. O zero veio de tipo, quartos ou vagas -- nenhum deles a RN-09.3
    relaxa. A segunda consulta seria byte a byte igual a primeira."""
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, quartos_min=4)) is False


def test_teto_sozinho_ja_torna_relaxavel() -> None:
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, preco_max_centavos=40000000)) is True


def test_regiao_sozinha_ja_torna_relaxavel() -> None:
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, regioes=("trindade",))) is True


def test_piso_sozinho_ja_torna_relaxavel() -> None:
    """A faixa cede nas duas pontas (D3), entao o piso tambem e relaxavel."""
    assert e_relaxavel(FiltroDeBusca(operacao=Operacao.VENDA, preco_min_centavos=20000000)) is True
