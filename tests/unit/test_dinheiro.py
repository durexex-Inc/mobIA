from decimal import Decimal

import pytest

from mobia.domain.agente.dinheiro import (
    _RUIDO,
    FaixaDePreco,
    MotivoDaRecusa,
    Recusa,
    _faixa_de,
    _Valor,
    _valor_de,
    parsear,
)
from mobia.domain.agente.schemas import Intencao


@pytest.mark.parametrize(
    ("texto", "centavos", "tinha_marcador"),
    [
        ("500 mil", 50_000_000, True),
        ("500k", 50_000_000, True),
        ("R$ 500.000", 50_000_000, False),
        ("uns 500 mil", 50_000_000, True),
        ("1,5 milhao", 150_000_000, True),
        ("2 milhoes", 200_000_000, True),
        ("500", 50_000, False),
        ("cerca de 800 mil reais", 80_000_000, True),
    ],
)
def test_valor_unico(texto, centavos, tinha_marcador):
    assert _valor_de(texto) == _Valor(centavos=centavos, tinha_marcador=tinha_marcador)


@pytest.mark.parametrize("texto", ["", "o que der", "quinhentos mil", "sei la"])
def test_sem_numero_devolve_none(texto):
    """A gramatica e lista fixa: numero por extenso nao e resolvido, e isso e
    lacuna declarada da spec, nao bug."""
    assert _valor_de(texto) is None


def test_ponto_e_milhar_virgula_e_decimal():
    assert _valor_de("500.000").centavos == 50_000_000
    assert _valor_de("1,5").centavos == 150


def test_ruido_stripping_direto():
    """Testa remocao de ruido diretamente no regex, nao em valor final.

    _RUIDO e privado, mas testar a remocao direto e necessario porque o caminho
    publico (_valor_de) e insensivel ao ruido quando o numero esta presente:
    _NUMERO.search encontra a faixa de digitos independente de lixo na frente.
    Isto era o problema original: "R$ 500.000" nao limpava o "R$ " e o teste
    passava mesmo assim porque _NUMERO achava "500.000". O teste aqui valida
    o regex diretamente, forcando a falha se a limpeza regredir.
    """
    # Forma com espaco (era quebrada, precisava da fix r\$\s*)
    resultado_com_espaco = _RUIDO.sub(" ", "r$ 500.000".casefold())
    assert "r$" not in resultado_com_espaco

    # Forma sem espaco (ja funcionava, precisa nao regredir)
    resultado_sem_espaco = _RUIDO.sub(" ", "r$500".casefold())
    assert "r$" not in resultado_sem_espaco

    # Guarda: palavras inteiras com \b nao sao comidas (reaisimo, algumas, etc)
    assert _RUIDO.sub(" ", "reaisimo") == "reaisimo"
    assert _RUIDO.sub(" ", "algumas") == "algumas"


@pytest.mark.parametrize(
    ("texto", "fator_esperado"),
    [
        # Marcador "mil"
        ("500 mil", Decimal(1_000)),
        ("500k", Decimal(1_000)),
        # Marcador "milhao"
        ("1,5 milhao", Decimal(1_000_000)),
        ("2 milhoes", Decimal(1_000_000)),
        # Sem marcador
        ("500", Decimal(1)),
        ("R$ 500.000", Decimal(1)),
    ],
)
def test_fator_rastreia_multiplicador(texto, fator_esperado):
    """Verifica que fator rastreia o multiplicador de grandeza aplicado."""
    resultado = _valor_de(texto)
    assert resultado is not None
    assert resultado.fator == fator_esperado


@pytest.mark.parametrize(
    ("expressao", "minimo", "maximo"),
    [
        ("uns 500 mil", None, 50_000_000),
        ("ate 500 mil", None, 50_000_000),
        ("no maximo 500 mil", None, 50_000_000),
        ("a partir de 300 mil", 30_000_000, None),
        ("no minimo 300 mil", 30_000_000, None),
        ("acima de 300 mil", 30_000_000, None),
        ("entre 400 e 500 mil", 40_000_000, 50_000_000),
        ("de 300 a 450 mil", 30_000_000, 45_000_000),
        ("300 a 450 mil", 30_000_000, 45_000_000),
    ],
)
def test_direcao_e_faixa(expressao, minimo, maximo):
    assert _faixa_de(expressao) == FaixaDePreco(min_centavos=minimo, max_centavos=maximo)


def test_marcador_final_distribui_para_os_dois_lados():
    """A regra que a D2 do desenho protege: em "entre 400 e 500 mil" o `mil`
    vale para os dois. E o motivo de o modelo devolver a faixa inteira em vez
    de partir os limites -- partir e decisao de normalizacao."""
    assert _faixa_de("entre 400 e 500 mil") == FaixaDePreco(
        min_centavos=40_000_000, max_centavos=50_000_000
    )


def test_cada_lado_com_seu_proprio_marcador():
    assert _faixa_de("de 800 mil a 1,2 milhao") == FaixaDePreco(
        min_centavos=80_000_000, max_centavos=120_000_000
    )


def test_faixa_sem_numero_nenhum_devolve_none():
    assert _faixa_de("o que der") is None


def test_expressao_clara_de_compra_e_aceita():
    assert parsear("uns 500 mil", Intencao.COMPRA) == FaixaDePreco(max_centavos=50_000_000)


def test_numero_nu_abaixo_do_piso_e_ambiguo():
    """O caso da card: "uns 500" para compra nao e R$ 500, e o sistema nao
    deve adivinhar qual e."""
    assert parsear("uns 500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.AMBIGUA)


def test_magnitude_explicita_fora_da_banda_e_implausivel():
    assert parsear("2,5 milhoes", Intencao.ALUGUEL) == Recusa(MotivoDaRecusa.IMPLAUSIVEL)


def test_sem_numero_e_ilegivel():
    """ILEGIVEL mede o buraco da gramatica; os outros dois medem o lead."""
    assert parsear("quinhentos mil", Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)


def test_aluguel_aceita_valor_que_compra_recusaria():
    assert parsear("1500", Intencao.ALUGUEL) == FaixaDePreco(max_centavos=150_000)
    assert parsear("1500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.AMBIGUA)


def test_indefinida_usa_a_uniao_das_bandas():
    """Com marcador de grandeza, a banda frouxa e mesmo a uniao das duas:
    R$ 1.500 esta fora da banda de compra e dentro da de aluguel, e sob
    INDEFINIDA ele passa. O caso NU e outro -- ver o teste seguinte."""
    assert parsear("1,5 mil", Intencao.INDEFINIDA) == FaixaDePreco(max_centavos=150_000)
    assert parsear("1,5 mil", Intencao.COMPRA) == Recusa(MotivoDaRecusa.IMPLAUSIVEL)


def test_faixa_invertida_e_recusada():
    """D6 do desenho: faixa invertida e canario de bug do parser -- o caso
    mais provavel e o marcador ter se ligado ao lado errado. Reordenar em
    silencio calaria o sinal."""
    assert parsear("entre 500 e 400 mil", Intencao.COMPRA) == Recusa(
        MotivoDaRecusa.IMPLAUSIVEL
    )


def test_faixa_igual_nos_dois_lados_e_valida():
    obtido = parsear("exatamente 600 mil", Intencao.COMPRA)
    assert obtido == FaixaDePreco(max_centavos=60_000_000)


def test_piso_da_banda_e_inclusive():
    """O piso e o menor valor ACEITO, nao o maior valor recusado: exatamente
    em cima da fronteira tem que passar. Sem este teste, trocar `<` por `<=`
    no piso nao quebra nada -- foi visto passar os 40 testes sem pegar."""
    assert parsear("30000", Intencao.COMPRA) == FaixaDePreco(max_centavos=3_000_000)


def test_teto_da_banda_e_inclusive():
    """Espelho do teste do piso, do lado de cima: exatamente no teto tem que
    passar, nao ser tratado como acima dele."""
    assert parsear("1000000000", Intencao.COMPRA) == FaixaDePreco(
        max_centavos=100_000_000_000
    )


@pytest.mark.parametrize("intencao", [Intencao.SUPORTE_CONTRATO, Intencao.FORA_DE_ESCOPO])
def test_intencao_nao_monetaria_cai_na_banda_frouxa(intencao):
    """`_BANDAS.get` sem entrada para estes dois cai na uniao das bandas, e
    isso e decisao, nao acidente do `.get`. O valor abaixo prova que a
    escolha muda o resultado: R$ 1.500 fica abaixo do piso de COMPRA
    (implausivel la, porque tem marcador), mas dentro da banda frouxa
    (aceito aqui).

    Com marcador de proposito: o numero NU responde ao piso de COMPRA em toda
    intencao sem banda propria -- ver
    `test_numero_nu_sob_a_banda_frouxa_responde_ao_piso_de_compra`.

    `parsear` nao sabe que `campos_a_gravar` descarta FORA_DE_ESCOPO e grava
    SUPORTE_CONTRATO normalmente -- essa e uma decisao do filtro de
    gravacao, nao deste modulo. Ver comentario de `_BANDA_FROUXA`."""
    assert parsear("1,5 mil", intencao) == FaixaDePreco(max_centavos=150_000)


# --- Revisao final da branch: os defeitos que a suite anterior nao pegava ---


@pytest.mark.parametrize(
    "expressao",
    [
        # Linha digitavel de boleto: 47 digitos. O lead cola isto quando a
        # conversa chega em pagamento, e `_NUMERO` era `\d[\d.]*`, sem teto.
        "3419179001010435100479102015000889105000001500",
        "1" * 100,
        "9" * 29,  # o primeiro comprimento que estourava a precisao de 28
    ],
)
def test_numero_absurdamente_longo_e_recusado_sem_levantar(expressao):
    """O contrato mais duro deste modulo, e o que ele custava quando furava.

    `(valor * 100).quantize(...)` levanta `InvalidOperation` quando o
    resultado passa dos 28 digitos do contexto decimal. `InvalidOperation`
    esta na tupla de `except` do classificador, entao virava
    `RespostaInvalida`: mensagem em FAILED, `attempts` incrementado, worker
    repetindo a chamada paga e batendo no mesmo parse deterministico. **O
    lead nao recebia resposta nenhuma**, por causa de um campo opcional de
    enriquecimento.
    """
    assert parsear(expressao, Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)


@pytest.mark.parametrize(
    ("expressao", "minimo", "maximo"),
    [
        # A familia `de X ate Y`: portugues corrente, e cada uma destas
        # devolvia um MAXIMO de R$ 300.000 -- 40% abaixo do que o lead disse,
        # dentro da banda, gravado sem log. A direcao (`ate`) era testada
        # antes da faixa e engolia a expressao inteira.
        ("de 300 mil ate 500 mil", 30_000_000, 50_000_000),
        ("entre 300 mil ate 500 mil", 30_000_000, 50_000_000),
        ("300 mil ate 500 mil", 30_000_000, 50_000_000),
        # Esta perdia o maximo em vez do minimo, pelo mesmo mecanismo.
        ("a partir de 300 mil a 500 mil", 30_000_000, 50_000_000),
    ],
)
def test_faixa_vence_direcao(expressao, minimo, maximo):
    """Dois numeros ligados por conector enunciam os dois extremos, e uma
    palavra de direcao no meio nao apaga um deles."""
    assert _faixa_de(expressao) == FaixaDePreco(min_centavos=minimo, max_centavos=maximo)


@pytest.mark.parametrize(
    ("fala", "minimo", "maximo"),
    [
        # `evals/corpus/compra.yaml`, verbatim: o unico turno do corpus que
        # afirma piso, anotado min 300000 / max 450000. Devolvia max
        # R$ 300.000 e perdia o minimo -- o regex de faixa partia no "e" de
        # "minha faixa e de", o lado esquerdo ficava sem numero, e o ramo de
        # faixa era abandonado inteiro.
        (
            "minha faixa e de 300 a 450 mil, abaixo disso nao acho nada decente",
            30_000_000,
            45_000_000,
        ),
        ("meu orcamento e de 300 a 450 mil", 30_000_000, 45_000_000),
    ],
)
def test_faixa_sobrevive_a_prosa_em_volta(fala, minimo, maximo):
    assert _faixa_de(fala) == FaixaDePreco(min_centavos=minimo, max_centavos=maximo)


@pytest.mark.parametrize(
    "expressao",
    [
        # I1: numero nao-monetario colado a um marcador de outra clausula.
        # Devolvia R$ 120.000 (o lead disse 600 mil), dentro da banda.
        "apartamento de 120m2 ate 600 mil",
        "2 quartos ate 600 mil",
        # `evals/corpus/borda.yaml`, a fala inteira. Se o modelo recortar de
        # mais, o parser tem de dizer que nao deu conta em vez de casar o
        # primeiro numero que achar com o marcador do ultimo.
        (
            "quero comprar um apto de 2 quartos no butanta ate 600 mil, "
            "aceita financiamento? pode me mandar as opcoes?"
        ),
    ],
)
def test_numero_de_outra_clausula_nao_vira_orcamento(expressao):
    """Recusar custa uma repergunta; casar o numero errado custa um filtro de
    busca errado que ninguem atribui ao parser. Mesma assimetria da D6."""
    assert parsear(expressao, Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)


def test_o_recorte_certo_da_mesma_fala_de_borda_e_lido():
    """O par do teste acima: quando o modelo recorta a expressao de orcamento
    -- que e o que a D1 lhe pede --, ela e lida sem drama."""
    assert parsear("ate 600 mil", Intencao.COMPRA) == FaixaDePreco(max_centavos=60_000_000)


@pytest.mark.parametrize(
    ("com_acento", "sem_acento"),
    [
        ("no mínimo 300 mil", "no minimo 300 mil"),
        ("mínimo 300 mil", "minimo 300 mil"),
        ("até 500 mil", "ate 500 mil"),
        ("no máximo 500 mil", "no maximo 500 mil"),
    ],
)
def test_acento_na_palavra_de_direcao_nao_muda_o_lado(com_acento, sem_acento):
    """Quem digita e o lead, e `_MULTIPLICADORES` ja assumia isso.

    "no mínimo 300 mil" devolvia um MAXIMO de R$ 300.000 -- filtro invertido,
    valor dentro da banda, nada logado. As formas de maximo escapavam do
    sintoma so porque o fallback ja e maximo, o que torna o defeito ainda
    mais facil de nao ver.
    """
    assert _faixa_de(com_acento) == _faixa_de(sem_acento)
    assert _faixa_de(com_acento) is not None


def test_numero_nu_sob_a_banda_frouxa_responde_ao_piso_de_compra():
    """A lacuna que a spec declarava e que esta revisao fechou.

    "uns 500" e o caso que abre o desenho desta card, e a INDEFINIDA e o
    momento comum da PRIMEIRA mencao de orcamento. Aceitar ali nao se corrige
    depois: `campos_a_gravar` nunca apaga e turno nenhum revalida, entao o
    valor sobrevive para dentro de uma conversa depois classificada COMPRA e
    vira o filtro da busca la.
    """
    assert parsear("uns 500", Intencao.INDEFINIDA) == Recusa(MotivoDaRecusa.AMBIGUA)
    assert parsear("1500", Intencao.INDEFINIDA) == Recusa(MotivoDaRecusa.AMBIGUA)
    # A regra e da banda frouxa, e nao de INDEFINIDA: os outros dois membros
    # respondem igual.
    assert parsear("1500", Intencao.SUPORTE_CONTRATO) == Recusa(MotivoDaRecusa.AMBIGUA)
    # E nao vaza para quem tem banda propria: aluguel continua aceitando o
    # numero nu, que e o motivo de a banda ser por intencao.
    assert parsear("1500", Intencao.ALUGUEL) == FaixaDePreco(max_centavos=150_000)


def test_cifrao_e_marcador_de_grandeza_para_a_regra_de_ambiguidade():
    """D3 lista `R$` entre os marcadores, e `_tinha_marcador` so olhava os
    multiplicadores. Os dois motivos apontam para lados opostos: "uns 500" e
    o lead impreciso; "R$ 500" e o lead dizendo a moeda de proposito e
    afirmando um valor que nao fecha com a intencao."""
    assert parsear("R$ 500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.IMPLAUSIVEL)
    assert parsear("uns 500", Intencao.COMPRA) == Recusa(MotivoDaRecusa.AMBIGUA)


def test_ponto_fora_da_forma_de_milhar_e_recusado():
    """"1.5 milhao" devolvia R$ 15.000.000 -- o ponto lido como milhar, 10x o
    que o lead disse, dentro da banda. Nao ha leitura pt-BR de "1.5", entao a
    saida e recusar, nao adivinhar entre 1 milhao e 1,5 milhao."""
    assert parsear("1.5 milhao", Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)
    # A forma legitima do lado de la continua lida.
    assert parsear("1,5 milhao", Intencao.COMPRA) == FaixaDePreco(max_centavos=150_000_000)
    assert parsear("R$ 1.234.567,89", Intencao.COMPRA) == FaixaDePreco(max_centavos=123_456_789)


def test_sinal_negativo_nao_e_descartado():
    """"-500 mil" virava R$ 500.000, dentro da banda, gravado em silencio."""
    assert parsear("-500 mil", Intencao.COMPRA) == Recusa(MotivoDaRecusa.ILEGIVEL)


def test_bilhao_e_lido_em_vez_de_virar_dois_reais():
    """Sem `bilhao` na gramatica, "2 bilhoes" resolvia para R$ 2,00 e era
    logado como AMBIGUA -- culpa do lead, por um buraco do parser. O teto da
    banda e R$ 1 bilhao, entao a gramatica precisa saber dizer o proprio
    limite dela."""
    assert parsear("1 bilhao", Intencao.COMPRA) == FaixaDePreco(max_centavos=100_000_000_000)
    assert parsear("2 bilhoes", Intencao.COMPRA) == Recusa(MotivoDaRecusa.IMPLAUSIVEL)
