from decimal import Decimal
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao
from mobia.evals.corpus import carregar, total_de_turnos
from mobia.evals.metricas import (
    PISO_DE_PRECISAO_DA_EXTRACAO_PCT,
    PISO_DE_TURNOS,
    PISO_DE_TURNOS_NEGATIVOS,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    Discrepancia,
    ExtracaoObservada,
    Faixa,
    ResumoDeNegativos,
    acuracia_de_intencao,
    acuracia_efetiva,
    bloqueia,
    discrepancias_da_extracao,
    erros,
    faixa_de,
    matriz_de_confusao,
    precisao_da_extracao,
    resumo_de_confianca,
    resumo_de_negativos,
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
    piso contra as conversas mais longas do corpus.

    Enquanto essa conta fechar, os dois limites medem coisas diferentes sem se
    atropelar -- o teto reprova "a rede caiu", o piso reprova "sobrou amostra
    de menos", e nunca os dois pela mesma causa. Se o corpus mudar de forma
    (conversas mais longas, ou menos folga sobre o piso), o abandono passa a
    poder furar o piso tambem, e a mensagem que o CI mostra vira a de quem for
    verificado primeiro em vez da causa real. Este teste falha exatamente ai,
    e de graca -- sem chamada paga.

    A perda maxima e a **soma das `TETO` conversas mais longas**, e nao
    `TETO x a mais longa`. As duas contas davam o mesmo numero enquanto havia
    cinco ou mais conversas no comprimento maximo; a TEC-239 deu um quarto
    turno a duas conversas e so a duas, e ai `5 x 4 = 20` passou a inventar
    tres turnos de perda que abandono nenhum consegue causar. A soma dos cinco
    maiores e o pior caso exato -- abandonar cinco conversas custa no maximo
    as cinco mais longas --, entao a troca deixa o teste mais preciso, nao
    mais frouxo: ele continua reprovando qualquer corpus em que o abandono de
    fato alcance o piso.
    """
    conversas = carregar(CORPUS)
    mais_longas = sorted((len(conversa.turnos) for conversa in conversas), reverse=True)

    pior_perda = sum(mais_longas[:TETO_DE_CONVERSAS_ABANDONADAS])

    assert total_de_turnos(conversas) - pior_perda >= PISO_DE_TURNOS, (
        f"as {TETO_DE_CONVERSAS_ABANDONADAS} conversas mais longas somam "
        f"{pior_perda} turnos, e o corpus tem {total_de_turnos(conversas)} "
        f"sobre um piso de {PISO_DE_TURNOS}"
    )


def test_o_piso_de_negativos_sobrevive_ao_teto_de_abandono() -> None:
    """O piso nao e numero de gosto: e o que sobra depois do pior abandono.

    Mesma conta de `test_o_teto_de_abandono_nunca_consegue_furar_o_piso_de_turnos`,
    na dimensao dos negativos. Se o corpus mudar de forma, este teste falha
    de graca, antes de qualquer chamada paga.
    """
    conversas = carregar(CORPUS)
    por_conversa = sorted((sum(1 for t in c.turnos if t.negativo) for c in conversas), reverse=True)
    negativos = sum(por_conversa)
    pior_perda = sum(por_conversa[:TETO_DE_CONVERSAS_ABANDONADAS])

    assert negativos - pior_perda >= PISO_DE_TURNOS_NEGATIVOS, (
        f"as {TETO_DE_CONVERSAS_ABANDONADAS} conversas com mais negativos somam "
        f"{pior_perda}, e o corpus tem {negativos} sobre um piso de "
        f"{PISO_DE_TURNOS_NEGATIVOS}"
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


def _observada(esperado, obtido, *, indice=0):
    return ExtracaoObservada(
        conversa_id="compra-01", indice=indice, esperado=esperado, obtido=obtido
    )


def test_extracao_perfeita_e_cem_por_cento():
    resultado = precisao_da_extracao(
        [_observada({"quartos": 2, "regiao": "zona sul"}, {"quartos": 2, "regiao": "zona sul"})]
    )
    assert (resultado.acertos, resultado.total) == (2, 2)
    assert resultado.faixa is Faixa.VERDE


def test_campo_esperado_que_nao_veio_conta_erro():
    resultado = precisao_da_extracao([_observada({"quartos": 2, "vagas": 1}, {"quartos": 2})])
    assert (resultado.acertos, resultado.total) == (1, 2)


def test_campo_inventado_conta_erro():
    """Sem isto, extrair o certo mais quatro campos inventados daria 100%."""
    resultado = precisao_da_extracao(
        [_observada({"quartos": 2}, {"quartos": 2, "vagas": 3, "regiao": "moema"})]
    )
    assert (resultado.acertos, resultado.total) == (1, 3)


def test_nao_extrair_nada_nao_da_cem_por_cento():
    """Sem isto, um modelo que nunca extrai passaria no piso."""
    resultado = precisao_da_extracao([_observada({"quartos": 2, "regiao": "zona sul"}, {})])
    assert (resultado.acertos, resultado.total) == (0, 2)
    assert resultado.faixa is Faixa.VERMELHO


def test_valor_errado_no_campo_certo_conta_erro():
    resultado = precisao_da_extracao([_observada({"quartos": 2}, {"quartos": 3})])
    assert (resultado.acertos, resultado.total) == (0, 1)


def test_regiao_compara_sem_ligar_para_caixa_nem_espaco():
    resultado = precisao_da_extracao([_observada({"regiao": "Zona Sul"}, {"regiao": " zona sul "})])
    assert (resultado.acertos, resultado.total) == (1, 1)


def test_preco_compara_por_valor_e_nao_por_texto():
    """600000 e Decimal("600000.00") sao o mesmo preco."""
    resultado = precisao_da_extracao(
        [_observada({"faixa_preco_max": 600000}, {"faixa_preco_max": Decimal("600000.00")})]
    )
    assert (resultado.acertos, resultado.total) == (1, 1)


def test_piso_da_extracao_e_oitenta_e_cinco():
    assert PISO_DE_PRECISAO_DA_EXTRACAO_PCT == 85


def test_faixa_da_extracao_usa_o_piso_proprio():
    """84 de 100 e o unico ponto que discrimina os dois pisos.

    Com o piso geral (84) seria AMARELO; com o piso da extracao (85) e
    VERMELHO. Testar 85/100 nao provaria nada: 85 passa nos dois pisos, e o
    teste continuaria verde se alguem esquecesse de passar `piso=`.
    """
    observadas = [_observada({"quartos": 2}, {"quartos": 2}, indice=i) for i in range(84)]
    observadas += [_observada({"quartos": 2}, {"quartos": 3}, indice=84 + i) for i in range(16)]
    resultado = precisao_da_extracao(observadas)
    assert (resultado.acertos, resultado.total) == (84, 100)
    assert resultado.faixa is Faixa.VERMELHO
    # A prova de que o piso e a unica diferenca: o mesmo par no piso geral sobe.
    assert faixa_de(84, 100) is Faixa.AMARELO


def test_nada_medido_nao_e_sucesso():
    with pytest.raises(ValueError):
        precisao_da_extracao([])


def test_faixa_de_continua_com_os_defaults_de_antes():
    """A parametrizacao nao pode mudar nenhuma chamada existente."""
    assert faixa_de(90, 100) is Faixa.VERDE
    assert faixa_de(84, 100) is Faixa.AMARELO
    assert faixa_de(83, 100) is Faixa.VERMELHO


# --- TEC-239: discrepancias por campo, para saber o que anotar --------------


def test_campo_obtido_sem_anotacao_e_extra():
    """O lado que acusa corpus: o modelo extraiu, ninguem anotou."""
    obtidas = discrepancias_da_extracao([_observada({"quartos": 2}, {"quartos": 2, "vagas": 1})])
    assert obtidas == [Discrepancia(conversa_id="compra-01", indice=0, campo="vagas", tipo="extra")]


def test_campo_anotado_que_nao_veio_e_faltou():
    """O lado que acusa modelo ou prompt."""
    obtidas = discrepancias_da_extracao(
        [_observada({"quartos": 2, "regiao": "sp"}, {"quartos": 2})]
    )
    assert obtidas == [
        Discrepancia(conversa_id="compra-01", indice=0, campo="regiao", tipo="faltou")
    ]


def test_campo_nos_dois_com_valor_diferente_divergiu():
    obtidas = discrepancias_da_extracao([_observada({"quartos": 2}, {"quartos": 3})])
    assert obtidas == [
        Discrepancia(conversa_id="compra-01", indice=0, campo="quartos", tipo="divergiu")
    ]


def test_acerto_nao_gera_discrepancia():
    assert discrepancias_da_extracao([_observada({"quartos": 2}, {"quartos": 2})]) == []


def test_normalizacao_de_comparavel_vale_aqui_tambem():
    """Se `_comparavel` nao fosse usado, isto viraria uma divergencia falsa e
    mandaria alguem "corrigir" uma anotacao que esta certa."""
    assert (
        discrepancias_da_extracao([_observada({"regiao": "Zona Sul"}, {"regiao": " zona sul "})])
        == []
    )
    assert (
        discrepancias_da_extracao(
            [_observada({"faixa_preco_max": 600000}, {"faixa_preco_max": Decimal("600000.00")})]
        )
        == []
    )


def test_acertos_mais_discrepancias_fecham_o_total_da_metrica():
    """A invariante que amarra as duas funcoes.

    Sem ela, alguem muda a formula de `precisao_da_extracao` e o relatorio passa
    a mentir em silencio, em vez de o teste quebrar.
    """
    observadas = [
        _observada({"quartos": 2, "regiao": "sp"}, {"quartos": 2, "vagas": 1}, indice=0),
        _observada({"urgencia": "IMEDIATA"}, {"urgencia": "SEM_PRESSA"}, indice=1),
        _observada({"tipo_imovel": "CASA"}, {"tipo_imovel": "CASA"}, indice=2),
    ]
    metrica = precisao_da_extracao(observadas)
    assert metrica.total is not None and metrica.acertos is not None
    assert metrica.acertos + len(discrepancias_da_extracao(observadas)) == metrica.total


def test_a_ordem_segue_a_dos_turnos_observados():
    """Quem for anotar le a lista de cima para baixo; ela tem de acompanhar a
    conversa, nao a ordem arbitraria de um `set`."""
    observadas = [
        _observada({}, {"vagas": 1}, indice=5),
        _observada({}, {"urgencia": "IMEDIATA"}, indice=2),
    ]
    assert [d.indice for d in discrepancias_da_extracao(observadas)] == [5, 2]


# --- TEC-238: invencao em turno negativo -----------------------------------


def test_modelo_que_inventa_em_turno_negativo_nao_tira_cem_por_cento() -> None:
    """O exploit que a card existe para fechar.

    Um modelo que acerta os turnos anotados e inventa `regiao`/`tipo_imovel`
    em todo turno nao anotado tirava 100%, VERDE. Com turnos negativos no
    corpus, a mesma invencao entra no denominador pelo lado obtido e nao tem
    como somar acerto.
    """
    observadas = [
        _observada({"quartos": 2}, {"quartos": 2}, indice=0),
        _observada({}, {"regiao": "sp", "tipo_imovel": "CASA"}, indice=1),
    ]

    metrica = precisao_da_extracao(observadas)

    assert (metrica.acertos, metrica.total) == (1, 3)
    assert metrica.faixa is Faixa.VERMELHO


def test_turno_negativo_sem_invencao_nao_altera_a_nota() -> None:
    """Nao inventar nao pode custar nem render ponto: o turno negativo limpo
    contribui zero para os dois lados da fracao. Sem isso, anotar mais
    negativos diluiria a nota de um modelo que se comporta."""
    so_positivo = [_observada({"quartos": 2}, {"quartos": 2}, indice=0)]
    com_negativo = [*so_positivo, _observada({}, {}, indice=1)]

    assert precisao_da_extracao(com_negativo).acertos == precisao_da_extracao(so_positivo).acertos
    assert precisao_da_extracao(com_negativo).total == precisao_da_extracao(so_positivo).total


def test_invencao_em_turno_negativo_e_extra_sem_ambiguidade() -> None:
    """O que torna o diagnostico suficiente sem uma metrica separada.

    Em turno positivo, `extra` pode ser invencao ou lacuna de anotacao. Em
    turno negativo nao pode ser lacuna: o turno esta anotado por completo.
    """
    achadas = discrepancias_da_extracao([_observada({}, {"regiao": "sp"}, indice=0)])

    assert [(d.campo, d.tipo) for d in achadas] == [("regiao", "extra")]


def test_corpus_so_negativo_e_limpo_levanta_em_vez_de_reportar() -> None:
    """A borda que o piso de negativos NAO protege.

    Turno negativo limpo contribui zero para os dois lados, entao um conjunto
    so de negativos sem invencao nenhuma tem total zero, e `faixa_de` recusa
    total zero para que um corpus que falhou ao carregar nao abra o gate com
    0/0. Quem impede esse conjunto de chegar aqui e `PISO_DE_TURNOS_ANOTADOS`,
    contado sobre positivos -- este teste fixa que a protecao mora la, e nao
    numa tolerancia escondida aqui dentro.
    """
    with pytest.raises(ValueError, match="nada medido"):
        precisao_da_extracao([_observada({}, {}, indice=0)])


def test_resumo_de_negativos_conta_turnos_e_invencoes() -> None:
    """Turno negativo sem invencao nao aparece em `discrepancias_da_extracao`,
    entao o relatorio nao teria como dizer quantos foram medidos. Sem esse
    numero, "3 invencoes" nao se distingue de "3 invencoes em 3 turnos"."""
    observadas = [
        _observada({"quartos": 2}, {"quartos": 2}, indice=0),
        _observada({}, {}, indice=1),
        _observada({}, {"regiao": "sp", "tipo_imovel": "CASA"}, indice=2),
    ]

    resumo = resumo_de_negativos(observadas)

    assert resumo == ResumoDeNegativos(turnos=2, com_invencao=1, campos_inventados=2)
