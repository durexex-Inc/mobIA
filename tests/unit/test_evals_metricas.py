from decimal import Decimal
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.corpus import carregar, total_de_turnos
from mobia.evals.metricas import (
    PISO_DE_TURNOS,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    Faixa,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    erros,
    faixa_de,
    matriz_de_confusao,
    resumo_de_confianca,
    sem_mecanismo,
)

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "corpus"

# Acima do limiar: a intencao efetiva e o proprio palpite, entao a confianca
# sai do caminho e o teste mede so o que quer medir.
CONFIANTE = Decimal("0.90")
# Abaixo do limiar: producao rebaixaria este palpite para INDEFINIDA.
INSEGURA = Decimal("0.50")


def classificacao(
    esperada: Intencao,
    obtida: Intencao,
    *,
    confianca: Decimal = CONFIANTE,
    conversa_id: str = "c-01",
    indice: int = 0,
) -> Classificacao:
    return Classificacao(
        conversa_id=conversa_id,
        indice=indice,
        esperada=esperada,
        obtida=obtida,
        confianca=confianca,
    )


@pytest.mark.parametrize(
    ("acertos", "total", "esperada"),
    [
        (135, 150, Faixa.VERDE),  # exatamente 90%
        (134, 150, Faixa.AMARELO),  # um abaixo do alvo
        (126, 150, Faixa.AMARELO),  # exatamente 84%, o piso -- ainda passa
        (125, 150, Faixa.VERMELHO),  # um abaixo do piso
        (150, 150, Faixa.VERDE),
        (0, 150, Faixa.VERMELHO),
    ],
)
def test_bordas_exatas_da_faixa(acertos: int, total: int, esperada: Faixa) -> None:
    """As bordas sao o unico lugar onde a faixa pode estar errada.

    126/150 e exatamente 84%, o piso, e 135/150 exatamente 90%, o alvo. Os
    dois casos passam em float tambem (`126/150 >= 0.84` e True) -- a
    aritmetica inteira nao esta aqui para consertar uma borda que float
    erraria, e sim para que a corretude na borda seja obvia por construcao em
    vez de depender de conferir a representacao binaria de cada literal.
    O que este teste guarda e o sentido de cada comparacao: `>=` no alvo e no
    piso, e nao `>`.
    """
    assert faixa_de(acertos, total) is esperada


def test_total_zero_e_erro_e_nao_verde() -> None:
    """Nada medido nao e sucesso. Sem esta guarda, um corpus que falhou ao
    carregar produziria 0/0 e o gate abriria."""
    with pytest.raises(ValueError):
        faixa_de(0, 0)


def test_acuracia_conta_acertos_por_turno() -> None:
    classificacoes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0),
        classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=1),
    ]

    resultado = acuracia_de_intencao(classificacoes)

    assert resultado.acertos == 1
    assert resultado.total == 2
    assert resultado.faixa is Faixa.VERMELHO


def test_matriz_agrupa_esperada_contra_obtida() -> None:
    """Saber que a acuracia caiu nao diz o que fazer. Saber que INVESTIMENTO
    vira COMPRA, sim."""
    classificacoes = [
        classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, conversa_id="c-01"),
        classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, conversa_id="c-02"),
        classificacao(Intencao.INVESTIMENTO, Intencao.INVESTIMENTO, conversa_id="c-03"),
    ]

    matriz = matriz_de_confusao(classificacoes)

    assert matriz[Intencao.INVESTIMENTO][Intencao.COMPRA] == 2
    assert matriz[Intencao.INVESTIMENTO][Intencao.INVESTIMENTO] == 1


def test_matriz_agrupa_pelo_palpite_cru_e_nao_pela_efetiva() -> None:
    """A matriz diz para onde a intencao escorreu, e isso e sobre o
    classificador. Se ela agrupasse pela efetiva, este caso viraria uma
    contagem em INDEFINIDA e ninguem saberia que o palpite foi COMPRA."""
    classificacoes = [classificacao(Intencao.INVESTIMENTO, Intencao.COMPRA, confianca=INSEGURA)]

    matriz = matriz_de_confusao(classificacoes)

    assert matriz[Intencao.INVESTIMENTO] == {Intencao.COMPRA: 1}


def test_metrica_sem_mecanismo_nunca_e_verde_e_nunca_bloqueia() -> None:
    """As duas metades importam. Verde esconderia que a metrica nao mede nada;
    bloquear deixaria o gate permanentemente vermelho, e gate sempre vermelho
    e desligado em uma semana.
    """
    metrica = sem_mecanismo("taxa de alucinacao", "bloqueada pela TEC-161")

    assert metrica.faixa is Faixa.SEM_MECANISMO
    assert metrica.faixa is not Faixa.VERDE
    assert metrica.acertos is None
    assert not bloqueia([metrica])


def test_apenas_vermelho_bloqueia() -> None:
    verde = acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.COMPRA)])
    vermelho = acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.ALUGUEL)])

    assert not bloqueia([verde])
    assert bloqueia([vermelho])
    assert bloqueia([verde, vermelho])


def test_acuracia_efetiva_conta_o_palpite_rebaixado_como_erro() -> None:
    """O palpite esta certo e producao nao o usa: abaixo do limiar,
    `executar_turno` responde com a pergunta de desambiguacao. A acuracia crua
    ve um acerto; a efetiva ve o que o lead recebeu."""
    classificacoes = [classificacao(Intencao.COMPRA, Intencao.COMPRA, confianca=INSEGURA)]

    assert acuracia_de_intencao(classificacoes).acertos == 1
    assert acuracia_efetiva(classificacoes).acertos == 0


def test_acuracia_efetiva_respeita_a_borda_fechada_por_cima_do_limiar() -> None:
    """`>= LIMIAR` nao desambigua, e "confianca exatamente 0,6 nao desambigua"
    e criterio de aceite do TEC-135. O eval le o limiar de producao pela
    `intencao_efetiva`, entao esta borda tem de ser a mesma nos dois lados --
    e ela e a que uma reimplementacao com `<=` erraria em silencio.
    """
    na_borda = [classificacao(Intencao.COMPRA, Intencao.COMPRA, confianca=LIMIAR_DE_DESAMBIGUACAO)]

    assert acuracia_efetiva(na_borda).acertos == 1


def test_a_catastrofe_de_calibragem_bloqueia_com_a_crua_verde() -> None:
    """A regressao que motiva a metrica, no tamanho em que ela acontece.

    O ajuste de prompt joga a confianca de **todo** turno abaixo do limiar. O
    palpite cru continua perfeito, entao a acuracia crua fica VERDE; producao
    desambigua em 100% dos turnos. Sem esta metrica o gate abriria.
    """
    classificacoes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=i, confianca=INSEGURA)
        for i in range(10)
    ]

    crua = acuracia_de_intencao(classificacoes)
    efetiva = acuracia_efetiva(classificacoes)

    assert crua.faixa is Faixa.VERDE
    assert efetiva.acertos == 0
    assert efetiva.faixa is Faixa.VERMELHO
    assert bloqueia([crua, efetiva])


def test_degradacao_parcial_de_calibragem_bloqueia() -> None:
    """Este teste era o inverso, e a inversao e o ganho da baseline.

    Com o piso proprio de 50%, metade do corpus rebaixado dava exatamente 50%
    e passava: a degradacao parcial aparecia so no relatorio, e isso estava
    declarado como limitacao. Desde que a efetiva herdou `PISO_DE_BLOQUEIO_PCT`
    ela bloqueia -- metade rebaixada da 50%, muito abaixo de 84%.

    Meia calibragem perdida e metade dos leads recebendo pergunta em vez de
    atendimento. Nao deveria caber num gate verde, e nao cabe mais.
    """
    confiantes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=i, confianca=CONFIANTE)
        for i in range(5)
    ]
    inseguras = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=5 + i, confianca=INSEGURA)
        for i in range(5)
    ]
    classificacoes = confiantes + inseguras

    efetiva = acuracia_efetiva(classificacoes)

    assert efetiva.acertos == 5
    assert efetiva.faixa is Faixa.VERMELHO
    assert bloqueia([efetiva])


def test_acuracia_efetiva_pode_passar_da_crua_em_turno_indefinido() -> None:
    """Nao e bug: quando o rotulo e INDEFINIDA, rebaixar um palpite
    mal-confiante acerta o rotulo. Documentado por teste para que a
    desigualdade nao seja lida como inversao de sinal em algum lugar."""
    classificacoes = [classificacao(Intencao.INDEFINIDA, Intencao.COMPRA, confianca=INSEGURA)]

    assert acuracia_de_intencao(classificacoes).acertos == 0
    assert acuracia_efetiva(classificacoes).acertos == 1


def test_resumo_de_confianca_separa_rebaixado_de_recuperado() -> None:
    """Os tres numeros que a recalibragem do limiar precisa, e que nenhuma
    outra execucao produz."""
    classificacoes = [
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0, confianca=CONFIANTE),
        classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=1, confianca=INSEGURA),
        classificacao(Intencao.INDEFINIDA, Intencao.ALUGUEL, indice=2, confianca=INSEGURA),
        classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=3, confianca=CONFIANTE),
    ]

    resumo = resumo_de_confianca(classificacoes)

    assert resumo.turnos == 4
    assert resumo.abaixo_do_limiar == 2
    assert resumo.acertos_rebaixados == 1
    assert resumo.acertos_recuperados == 1


def test_erros_incluem_o_acerto_rebaixado_e_excluem_o_acerto_confiante() -> None:
    """O acerto rebaixado nao aparece na acuracia crua nem na matriz. Se
    tambem nao aparecesse aqui, o unico jeito de descobri-lo seria outra
    execucao paga."""
    confiante_certo = classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=0)
    rebaixado = classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=1, confianca=INSEGURA)
    errado = classificacao(Intencao.ALUGUEL, Intencao.COMPRA, indice=2)

    assert erros([confiante_certo, rebaixado, errado]) == [rebaixado, errado]


def test_o_teto_de_abandono_nunca_consegue_furar_o_piso_de_turnos() -> None:
    """O teto de conversas abandonadas nao e um numero de gosto: e a folga do
    piso dividida pela conversa mais longa do corpus.

    Enquanto essa conta fechar, os dois limites medem coisas diferentes sem se
    atropelar -- o teto reprova "a rede caiu", o piso reprova "sobrou amostra
    de menos", e nunca os dois pela mesma causa. Se o corpus mudar de forma
    (conversas mais longas, ou menos folga sobre o piso), o abandono passa a
    poder furar o piso tambem, e a mensagem que o CI mostra vira a de quem for
    verificado primeiro em vez da causa real. Este teste falha exatamente ai,
    e de graca -- sem chamada paga.
    """
    conversas = carregar(CORPUS)
    mais_longa = max(len(conversa.turnos) for conversa in conversas)

    pior_perda = TETO_DE_CONVERSAS_ABANDONADAS * mais_longa

    assert total_de_turnos(conversas) - pior_perda >= PISO_DE_TURNOS, (
        f"teto {TETO_DE_CONVERSAS_ABANDONADAS} x conversa mais longa "
        f"{mais_longa} = {pior_perda} turnos, e o corpus tem "
        f"{total_de_turnos(conversas)} sobre um piso de {PISO_DE_TURNOS}"
    )


def test_a_efetiva_usa_as_mesmas_faixas_da_crua() -> None:
    """O que a baseline mudou, fixado por teste.

    Antes a efetiva tinha faixa propria de duas saidas e nunca chegava a VERDE,
    porque nao havia alvo calibrado. A execucao de 2026-08-27 mediu 92,6%, e o
    alvo de 90% do criterio de aceite pertence a esta metrica ao menos tanto
    quanto a crua: e a intencao efetiva que o lead experimenta.

    Os tres casos abaixo sao as mesmas bordas de `faixa_de`, verificadas pela
    metrica de ponta a ponta -- se alguem devolver um piso proprio, algum
    deles falha.
    """

    def efetiva_com(acertos: int, total: int) -> Faixa:
        certas = [
            classificacao(Intencao.COMPRA, Intencao.COMPRA, indice=i, confianca=CONFIANTE)
            for i in range(acertos)
        ]
        erradas = [
            classificacao(
                Intencao.COMPRA, Intencao.ALUGUEL, indice=acertos + i, confianca=CONFIANTE
            )
            for i in range(total - acertos)
        ]
        return acuracia_efetiva(certas + erradas).faixa

    assert efetiva_com(90, 100) is Faixa.VERDE
    assert efetiva_com(84, 100) is Faixa.AMARELO
    assert efetiva_com(83, 100) is Faixa.VERMELHO
