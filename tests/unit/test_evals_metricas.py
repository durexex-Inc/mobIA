from dataclasses import fields
from decimal import Decimal
from pathlib import Path

import pytest

from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Extracao, Intencao
from mobia.evals.corpus import carregar, total_de_turnos
from mobia.evals.metricas import (
    ALVO_DE_ADERENCIA_AO_TOM_PCT,
    CAMPOS_DA_EXTRACAO,
    DISPERSAO_MEDIDA,
    MARCADORES_DE_REPERGUNTA,
    MAX_CARACTERES_DA_RESPOSTA,
    PISO_DE_ADERENCIA_AO_TOM_PCT,
    PISO_DE_BLOQUEIO_PCT,
    PISO_DE_PRECISAO_DA_EXTRACAO_PCT,
    PISO_DE_TURNOS,
    PISO_DE_TURNOS_NEGATIVOS,
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    Discrepancia,
    EstadoDaConversa,
    ExtracaoObservada,
    Faixa,
    PerguntaObservada,
    RespostaObservada,
    ResumoDeNegativos,
    acuracia_de_intencao,
    acuracia_efetiva,
    aderencia_ao_tom,
    bloqueia,
    campos_perguntados,
    decomposicao_da_extracao,
    discrepancias_da_extracao,
    eh_negativo,
    erros,
    faixa_de,
    insistencias,
    matriz_de_confusao,
    precisao_da_extracao,
    precisao_efetiva_da_extracao,
    resumo_de_confianca,
    resumo_de_negativos,
    resumo_do_formato,
    sem_mecanismo,
    violacoes_de_formato,
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
        [
            _observada(
                {"faixa_preco_max_centavos": 600000},
                {"faixa_preco_max_centavos": Decimal("600000.00")},
            )
        ]
    )
    assert (resultado.acertos, resultado.total) == (1, 1)


def test_a_decomposicao_fecha_com_a_metrica_que_trava():
    """O invariante que impede as duas contas de divergirem em silencio.

    `decomposicao_da_extracao` refaz a varredura de `precisao_da_extracao` em
    vez de reaproveita-la, para aplicar `_comparavel` do mesmo jeito. Duas
    formulas do mesmo criterio divergem, e a divergencia so aparece na borda:
    este teste e o que faz ela aparecer aqui em vez de numa execucao paga.
    """
    observadas = [
        _observada({"quartos": 2, "vagas": 1}, {"quartos": 2, "regiao": "moema"}),
        _observada({"regiao": "Zona Sul"}, {"regiao": " zona sul "}, indice=1),
        _observada({"quartos": 2}, {"quartos": 3}, indice=2),
        _observada({}, {"urgencia": "IMEDIATA"}, indice=3),
    ]
    metrica = precisao_da_extracao(observadas)
    decomposicao = decomposicao_da_extracao(observadas)

    assert decomposicao.acertos == metrica.acertos
    # O denominador de uniao e a base fixa mais o que o modelo inventou.
    assert decomposicao.anotados + decomposicao.extra == metrica.total
    # E a base fixa se fecha nas tres formas de um campo anotado terminar.
    assert (
        decomposicao.acertos + decomposicao.faltou + decomposicao.divergiu == decomposicao.anotados
    )


def test_a_base_fixa_nao_se_move_quando_o_modelo_inventa():
    """A razao de existir da decomposicao, num caso minimo.

    Inventar um campo derruba a metrica de uniao (de 1/1 para 1/2) e nao toca
    na base fixa. E isso, multiplicado por alguns campos, que faz a mesma
    arvore sair VERDE numa execucao e AMARELO na seguinte -- ver TEC-253.
    """
    sem_invencao = [_observada({"quartos": 2}, {"quartos": 2})]
    com_invencao = [_observada({"quartos": 2}, {"quartos": 2, "vagas": 3})]

    assert precisao_da_extracao(sem_invencao).total == 1
    assert precisao_da_extracao(com_invencao).total == 2

    assert decomposicao_da_extracao(sem_invencao).taxa_sobre_base_fixa == 1.0
    assert decomposicao_da_extracao(com_invencao).taxa_sobre_base_fixa == 1.0
    assert decomposicao_da_extracao(com_invencao).extra == 1


def test_taxa_sobre_base_fixa_e_none_sem_campo_anotado():
    """Turno negativo puro: a razao nao existe, e inventar zero nao e 100%."""
    decomposicao = decomposicao_da_extracao([_observada({}, {"vagas": 3})])
    assert decomposicao.anotados == 0
    assert decomposicao.taxa_sobre_base_fixa is None
    assert decomposicao.extra == 1


def test_a_dispersao_medida_e_do_par_de_execucoes_e_nao_um_palpite():
    """`DISPERSAO_MEDIDA` e resultado de experimento, nao constante de codigo.

    O teste existe para que mexer no numero exija encarar que ele veio de uma
    medicao datada: se alguem o alterar sem medir de novo, isto reprova e
    pergunta de onde veio o valor novo.
    """
    assert DISPERSAO_MEDIDA.data == "30/08/2026"
    assert DISPERSAO_MEDIDA.uniao_pp == pytest.approx(91.8 - 86.1, abs=0.05)
    assert DISPERSAO_MEDIDA.base_fixa_pp == pytest.approx(92.7 - 90.6, abs=0.05)
    # A uniao dispersa mais que a base fixa: e o achado inteiro da TEC-253.
    assert DISPERSAO_MEDIDA.uniao_pp > DISPERSAO_MEDIDA.base_fixa_pp


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
    assert obtidas == [
        Discrepancia(conversa_id="compra-01", indice=0, campo="vagas", tipo="extra", obtido=1)
    ]


def test_campo_anotado_que_nao_veio_e_faltou():
    """O lado que acusa modelo ou prompt."""
    obtidas = discrepancias_da_extracao(
        [_observada({"quartos": 2, "regiao": "sp"}, {"quartos": 2})]
    )
    assert obtidas == [
        Discrepancia(
            conversa_id="compra-01", indice=0, campo="regiao", tipo="faltou", esperado="sp"
        )
    ]


def test_campo_nos_dois_com_valor_diferente_divergiu():
    obtidas = discrepancias_da_extracao([_observada({"quartos": 2}, {"quartos": 3})])
    assert obtidas == [
        Discrepancia(
            conversa_id="compra-01",
            indice=0,
            campo="quartos",
            tipo="divergiu",
            esperado=2,
            obtido=3,
        )
    ]


def test_o_lado_ausente_de_uma_discrepancia_fica_none():
    """`None` e "este lado nao tinha valor", e nunca um valor real: o corpus
    recusa anotacao nula e `preenchidos()` nunca devolve `None`. Sem essa
    garantia o relatorio teria de distinguir ausencia de nulo, e nao tem
    como."""
    (extra,) = discrepancias_da_extracao([_observada({}, {"vagas": 1})])
    assert extra.esperado is None and extra.obtido == 1
    (faltou,) = discrepancias_da_extracao([_observada({"vagas": 1}, {})])
    assert faltou.esperado == 1 and faltou.obtido is None


def test_divergiu_guarda_os_dois_valores_crus():
    """Crus, e nao normalizados -- e a TEC-248 mostrou por que isso importa.

    A baseline de 30/08/2026 teve sete `divergiu` em `regiao` e nenhum valor
    guardado, entao ninguem sabia se o modelo errava a regiao ou se as duas
    formas so nao casavam. A sonda de nove chamadas respondeu: o modelo
    acertou o lugar nos sete, e devolvia "sao paulo" com acento onde o corpus
    anotava "sp", ou "avenida paulista" onde ele anotava "paulista". Eram
    seis defeitos de regua e uma anotacao errada -- zero erro do modelo.

    Nada disso teria sido legivel numa lista que so dissesse "regiao
    (divergiu)". Guardar a forma comparada tambem nao serviria: quem le a
    lista ja sabe que `_comparavel` rodou e nao reconciliou os dois -- e o
    que estar nesta lista significa.
    """
    (d,) = discrepancias_da_extracao([_observada({"regiao": "jardins"}, {"regiao": "moema"})])
    assert d.esperado == "jardins"
    assert d.obtido == "moema"


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
            [
                _observada(
                    {"faixa_preco_max_centavos": 600000},
                    {"faixa_preco_max_centavos": Decimal("600000.00")},
                )
            ]
        )
        == []
    )


# --- TEC-241: a medicao compara regiao na forma canonica --------------------


def test_regiao_com_preposicao_casa_com_o_toponimo():
    """O par que originou esta card: 10 das 29 discrepancias da execucao de
    28/08 eram `regiao`, todas `divergiu`, e nenhuma era erro do modelo."""
    observadas = [_observada({"regiao": "perto da usp"}, {"regiao": "usp"})]

    metrica = precisao_da_extracao(observadas)

    assert (metrica.acertos, metrica.total) == (1, 1)
    assert discrepancias_da_extracao(observadas) == []


def test_regiao_com_estacao_casa_com_o_bairro():
    observadas = [_observada({"regiao": "vila madalena"}, {"regiao": "estacao vila madalena"})]

    assert precisao_da_extracao(observadas).acertos == 1
    assert discrepancias_da_extracao(observadas) == []


def test_regioes_realmente_diferentes_continuam_divergindo():
    """A normalizacao nao pode fazer tudo casar com tudo -- ai ela deixaria de
    medir. `aluguel-02` troca de regiao no meio da conversa, e esse caso e o
    que prova que a sobrescrita e medida.

    `brooklin` x `itaim bibi` nao compartilha prefixo nenhum, entao so
    reprovaria sob um normalizador degenerado -- ele nao exercita o mecanismo
    de verdade, so confere que dois toponimos sem nada em comum continuam
    diferentes. `zona sul` x `zona leste` compartilham a palavra "zona", que e
    exatamente o tipo de prefixo que este modulo remove de outras referencias
    (`regiao `, `estacao `, …) e que `_PREFIXOS_DE_REFERENCIA` recusa de
    proposito remover aqui (ver comentario em `schemas.py`). Este par mede a
    metrica de ponta a ponta sobre um caso de forma real, no lugar de um par
    arbitrario -- a guarda contra "zona" virar prefixo removido continua
    sendo `test_normalizar_regiao_nao_come_zona`, no nivel da funcao; este
    teste garante que, enquanto essa guarda vale, a metrica tambem reflete a
    divergencia real entre duas zonas distintas.
    """
    observadas = [_observada({"regiao": "brooklin"}, {"regiao": "itaim bibi"})]

    assert precisao_da_extracao(observadas).acertos == 0
    assert [d.tipo for d in discrepancias_da_extracao(observadas)] == ["divergiu"]

    observadas_zona = [_observada({"regiao": "zona sul"}, {"regiao": "zona leste"})]

    assert precisao_da_extracao(observadas_zona).acertos == 0
    assert [d.tipo for d in discrepancias_da_extracao(observadas_zona)] == ["divergiu"]


def test_normalizacao_de_regiao_nao_vaza_para_outros_campos_de_texto():
    """So `regiao` e normalizada. Se `_comparavel` aplicasse a regra a todo
    texto, um campo futuro herdaria uma normalizacao pensada para toponimo."""
    from mobia.evals.metricas import _comparavel

    assert _comparavel("regiao", "perto da usp") == "usp"
    assert _comparavel("tipo_imovel", "perto da usp") == "perto da usp"


def test_acertos_mais_discrepancias_fecham_o_total_da_metrica():
    """A invariante que amarra as duas funcoes, com negativos na mistura.

    Sem ela, alguem muda a formula de `precisao_da_extracao` e o relatorio passa
    a mentir em silencio, em vez de o teste quebrar. O README aponta este teste
    pelo nome como a guarda da invariante "continua valendo com negativos" --
    as tres `observadas` originais eram todas positivas, e um negativo com
    invencao (`esperado={}`, `obtido` nao vazio) exercita exatamente o lado da
    uniao que so aparece desde a TEC-238: o campo entra no total pelo lado
    obtido e vira `extra`, nunca `acerto`. O negativo limpo prova a outra
    metade -- contribui zero para os dois lados e nao quebra a soma.
    """
    observadas = [
        _observada({"quartos": 2, "regiao": "sp"}, {"quartos": 2, "vagas": 1}, indice=0),
        _observada({"urgencia": "IMEDIATA"}, {"urgencia": "SEM_PRESSA"}, indice=1),
        _observada({"tipo_imovel": "CASA"}, {"tipo_imovel": "CASA"}, indice=2),
        _observada({}, {"regiao": "sp"}, indice=3),
        _observada({}, {}, indice=4),
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


def test_eh_negativo_e_o_criterio_unico_de_turno_negativo() -> None:
    """`eh_negativo` e o que `resumo_de_negativos` e `_positivas_e_negativas`
    (`evals/test_acuracia_de_intencao.py`) tem de compartilhar -- duas formulas
    do mesmo criterio divergem sem teste para acusar, o mesmo furo que matou
    `faixa_de_catastrofe` no PR #10."""
    assert eh_negativo(_observada({}, {}, indice=0)) is True
    assert eh_negativo(_observada({}, {"regiao": "sp"}, indice=0)) is True
    assert eh_negativo(_observada({"quartos": 2}, {"quartos": 2}, indice=0)) is False


def _estado(esperado, obtido, *, conversa_id="compra-06"):
    return EstadoDaConversa(conversa_id=conversa_id, esperado=esperado, obtido=obtido)


def test_reafirmacao_nao_reemitida_nao_e_erro_no_estado():
    """O caso que motivou a metrica, e a metade "reafirmou de menos".

    Em `compra-06` o lead diz "cobertura" nos tres turnos e o corpus anota
    `tipo_imovel` nos tres. O modelo extrai no primeiro e devolve `null` nos
    outros dois -- corretamente, porque "qual o valor do condominio dessa
    cobertura?" pressupoe em vez de afirmar, e a regra do prompt manda extrair
    so o que a fala afirma. `precisao_da_extracao` conta dois `faltou`;
    `campos_a_gravar` nao apaga, entao o estado carrega APARTAMENTO desde o
    primeiro turno e o lead nunca vive esses dois erros.
    """
    resumo = precisao_efetiva_da_extracao(
        [_estado({"tipo_imovel": "APARTAMENTO"}, {"tipo_imovel": "APARTAMENTO"})]
    )
    assert (resumo.acertos, resumo.total) == (1, 1)
    assert resumo.divergencias == []


def test_campo_extraido_num_turno_sem_anotacao_nao_e_erro_no_estado():
    """A outra metade: "reafirmou de mais", ou cedo demais.

    Em `follow-up-08` o corpus anota `urgencia` no turno 1 e o modelo a extrai
    no turno 0. Turno a turno isso e `extra` -- invencao --, e no estado final
    e simplesmente o valor certo. A metrica por turno pune o modelo por
    acertar cedo; esta nao.
    """
    resumo = precisao_efetiva_da_extracao(
        [_estado({"urgencia": "IMEDIATA"}, {"urgencia": "IMEDIATA"}, conversa_id="follow-up-08")]
    )
    assert (resumo.acertos, resumo.total) == (1, 1)


def test_campo_que_nunca_foi_extraido_continua_erro():
    """A metrica efetiva nao e mais frouxa -- e mais especifica.

    `compra-10` tem um turno so, e o modelo nao extraiu
    `tem_imovel_para_vender`. Nao ha turno anterior que tenha gravado, entao o
    estado final sai errado e o lead vive o erro. Este e dos que sobram.
    """
    resumo = precisao_efetiva_da_extracao(
        [_estado({"tem_imovel_para_vender": False}, {}, conversa_id="compra-10")]
    )
    assert (resumo.acertos, resumo.total) == (0, 1)
    assert [(d.campo, d.tipo) for d in resumo.divergencias] == [
        ("tem_imovel_para_vender", "faltou")
    ]


def test_invencao_que_sobrevive_ate_o_fim_continua_erro():
    """Denominador de uniao, pelo mesmo motivo de `precisao_da_extracao`.

    Sem contar o inventado, um estado que acerta o anotado e carrega tres
    campos que ninguem anotou pontuaria igual a um limpo -- e o lead veria
    esses campos no estado de qualificacao.
    """
    resumo = precisao_efetiva_da_extracao([_estado({"quartos": 2}, {"quartos": 2, "vagas": 3})])
    assert (resumo.acertos, resumo.total) == (1, 2)
    assert [(d.campo, d.tipo) for d in resumo.divergencias] == [("vagas", "extra")]


def test_valor_errado_no_estado_final_e_divergencia():
    resumo = precisao_efetiva_da_extracao([_estado({"quartos": 2}, {"quartos": 3})])
    assert (resumo.acertos, resumo.total) == (0, 1)
    assert resumo.divergencias[0].tipo == "divergiu"
    assert (resumo.divergencias[0].esperado, resumo.divergencias[0].obtido) == (2, 3)


def test_estado_efetivo_usa_a_mesma_normalizacao_da_metrica_por_turno():
    """`regiao` tem contrato de forma proprio (TEC-241), e as duas contas
    precisam aplica-lo igual -- senao a efetiva acusaria divergencia onde a
    por turno ja tinha reconciliado."""
    resumo = precisao_efetiva_da_extracao(
        [_estado({"regiao": "Zona Sul"}, {"regiao": " zona sul "})]
    )
    assert (resumo.acertos, resumo.total) == (1, 1)


def test_taxa_e_none_sem_campo_nenhum():
    resumo = precisao_efetiva_da_extracao([_estado({}, {})])
    assert resumo.taxa is None


def test_campos_da_extracao_sai_da_dataclass_e_nao_de_lista_escrita_a_mao():
    """Um campo novo em `Extracao` tem de entrar aqui sozinho.

    O filtro existe porque `estado_acumulado` carrega tambem `intencao`, que
    `campos_a_gravar` poe e que nao e campo de extracao. Uma lista literal
    envelheceria calada no dia em que alguem acrescentasse um campo.
    """
    assert CAMPOS_DA_EXTRACAO == {campo.name for campo in fields(Extracao)}
    assert "intencao" not in CAMPOS_DA_EXTRACAO


def _resposta(texto: str, *, indice: int = 0) -> RespostaObservada:
    return RespostaObservada(conversa_id="compra-01", indice=indice, texto=texto)


def test_seiscentos_caracteres_passa_e_seiscentos_e_um_viola():
    """A borda do RN-04.2, nos dois lados. O teto e inclusivo."""
    assert violacoes_de_formato([_resposta("x" * MAX_CARACTERES_DA_RESPOSTA)]) == []

    violacoes = violacoes_de_formato([_resposta("x" * (MAX_CARACTERES_DA_RESPOSTA + 1))])
    assert [(v.regra, v.medido) for v in violacoes] == [("comprimento", 601)]


def test_duas_perguntas_passam_e_tres_violam():
    """A regua cobra o proposito da RN-04.2, e nao a leitura literal dela.

    O que a regra protege e "nunca um bloco com cinco perguntas" e "nao
    responder a um questionario". O teto de 1 marcava como violacao um padrao
    estavel de duas perguntas de qualificacao genuinas -- 28 turnos em 147 na
    execucao de 31/08 -- enquanto o bloco que ela teme nao aparecia. A TEC-255
    subiu o teto para 2, entao a borda que importa passa a ser a terceira.
    """
    assert violacoes_de_formato([_resposta("qual regiao voce prefere?")]) == []
    assert violacoes_de_formato([_resposta("perfeito, vou procurar.")]) == []
    assert violacoes_de_formato([_resposta("qual regiao? e quantos quartos?")]) == []

    violacoes = violacoes_de_formato([_resposta("qual regiao? quartos? vaga?")])
    assert [(v.regra, v.medido) for v in violacoes] == [("perguntas", 3)]


def test_turno_que_viola_as_duas_conta_como_um_turno_ruim():
    """A metrica e por resposta, nao por violacao.

    O lead vive o turno: um turno que estoura o tamanho **e** faz tres
    perguntas e um turno ruim, nao dois. Contar violacoes derrubaria a taxa
    abaixo do que o lead experimenta.
    """
    ruim = _resposta("x" * 700 + " a? b? c?")

    assert len(violacoes_de_formato([ruim])) == 2
    metrica = aderencia_ao_tom([ruim, _resposta("tudo certo.", indice=1)])
    assert (metrica.acertos, metrica.total) == (1, 2)


def test_a_metrica_e_a_lista_de_violacoes_nao_divergem():
    """As duas contas saem da mesma funcao, e este teste trava isso.

    `campos_a_gravar` e `_subcontagem` ja mostraram neste projeto o que
    acontece com duas copias da mesma regra: elas divergem, e a divergencia so
    aparece na borda.
    """
    respostas = [
        _resposta("x" * 601, indice=0),
        _resposta("a? b?", indice=1),
        _resposta("ok", indice=2),
        _resposta("x" * 800 + "?" * 3, indice=3),
    ]

    violadas = {(v.conversa_id, v.indice) for v in violacoes_de_formato(respostas)}
    metrica = aderencia_ao_tom(respostas)

    assert metrica.total - metrica.acertos == len(violadas)


def test_emoji_e_contado_mas_nao_reprova():
    """A regra de emoji do card **nao** e mecanizavel, e por isso nao entra na
    metrica.

    "A informacao essencial nunca depende de emoji" exige entender o que a
    frase afirma. Contar figurinha nao responde isso -- e reportar um numero
    que nao mede a regra seria pior que reportar nenhum, que e o raciocinio de
    `sem_mecanismo`.
    """
    com_emoji = _resposta("achei tres opcoes otimas para voce 🏠✨")

    assert violacoes_de_formato([com_emoji]) == []
    assert aderencia_ao_tom([com_emoji]).acertos == 1

    resumo = resumo_do_formato([com_emoji, _resposta("sem figurinha", indice=1)])
    assert (resumo.com_emoji, resumo.emojis) == (1, 2)


def test_o_piso_da_aderencia_deixou_de_ser_andaime():
    """A troca que o andaime pedia, feita com o numero na mao.

    O piso de 50 existia porque o texto do agente nunca tinha sido medido. A
    TEC-255 mediu, recalculando os dois relatorios de 31/08 sob o teto novo de
    perguntas: 144/147 (98,0%) e 146/147 (99,3%). O piso de 90 fica oito
    pontos abaixo do pior ponto observado -- a escolha conservadora, porque
    dois pontos de medicao sao pouco para um piso apertado, e um piso que abre
    VERMELHO sem regressao real e o erro que o andaime avisava.

    Este piso fica ACIMA de `PISO_DE_BLOQUEIO_PCT`, ao contrario do andaime, e
    isso e deliberado: 84 e o piso da acuracia de intencao, medido sobre outra
    coisa, e nao um teto para os pisos das metricas irmas.
    """
    assert PISO_DE_ADERENCIA_AO_TOM_PCT == 90
    assert PISO_DE_ADERENCIA_AO_TOM_PCT > PISO_DE_BLOQUEIO_PCT


def test_o_alvo_da_aderencia_e_proprio_e_nao_o_global():
    """Com alvo igual ao piso a faixa AMARELA desapareceria.

    `faixa_de` devolve VERDE em `>= alvo` e AMARELO em `>= piso`. Se esta
    metrica usasse o `ALVO_PCT` global de 90 junto do piso novo de 90, o
    segundo teste nunca seria alcancado: a metrica viraria binaria e passaria
    a bloquear o gate abaixo de 90 -- mais duro que o andaime que ela
    substitui, e o oposto de escolher o piso conservador.
    """
    assert ALVO_DE_ADERENCIA_AO_TOM_PCT == 98
    assert ALVO_DE_ADERENCIA_AO_TOM_PCT > PISO_DE_ADERENCIA_AO_TOM_PCT


def test_as_faixas_da_aderencia_saem_do_piso_e_do_alvo_proprios():
    """A faixa e comportamento, e nao so o valor de duas constantes.

    Sob o `ALVO_PCT` global de 90 e o andaime de 50, uma execucao de 95%
    sairia VERDE e uma de 89% sairia AMARELO. Com o alvo de 98 e o piso de 90
    as duas descem uma faixa, e e essa descida que a TEC-255 comprou.
    """

    def _faixa(acertos: int, total: int) -> Faixa:
        respostas = [_resposta("ok" if i < acertos else "a? b? c?", indice=i) for i in range(total)]
        return aderencia_ao_tom(respostas).faixa

    assert _faixa(98, 100) is Faixa.VERDE
    assert _faixa(95, 100) is Faixa.AMARELO
    assert _faixa(90, 100) is Faixa.AMARELO
    assert _faixa(89, 100) is Faixa.VERMELHO


def _perguntou(indice: int, *campos: str, conversa: str = "compra-14") -> PerguntaObservada:
    return PerguntaObservada(conversa_id=conversa, indice=indice, campos=frozenset(campos))


def test_campo_perguntado_em_dois_turnos_e_insistencia():
    """O caso que a execucao de 31/08 mostrou, no menor tamanho possivel."""
    resumo = insistencias([_perguntou(0, "regiao"), _perguntou(1, "regiao")])

    assert [(i.campo, i.turnos) for i in resumo.insistencias] == [("regiao", (0, 1))]


def test_campo_perguntado_uma_vez_so_nao_e_insistencia():
    """Perguntar uma vez e o trabalho do agente, nao defeito."""
    assert insistencias([_perguntou(0, "regiao"), _perguntou(1, "quartos")]).insistencias == []


def test_conversas_diferentes_nao_se_somam():
    """A insistencia e dentro da conversa. Dois leads perguntados sobre regiao
    uma vez cada nao viram um lead perguntado duas."""
    resumo = insistencias([_perguntou(0, "regiao"), _perguntou(0, "regiao", conversa="aluguel-01")])

    assert resumo.insistencias == []
    assert resumo.conversas == 2


def test_o_pior_caso_vem_primeiro():
    """Tres turnos seguidos e pior que dois, e quem le o relatorio precisa ver
    isso antes -- a lista pode ficar longa."""
    resumo = insistencias(
        [
            _perguntou(0, "vagas"),
            _perguntou(1, "vagas"),
            _perguntou(0, "regiao"),
            _perguntou(1, "regiao"),
            _perguntou(2, "regiao"),
        ]
    )

    assert [i.campo for i in resumo.insistencias] == ["regiao", "vagas"]
    assert resumo.insistencias[0].turnos == (0, 1, 2)


def test_conversas_afetadas_conta_conversa_e_nao_campo():
    """`compra-14` insistiu em dois campos e e UMA conversa incomodada."""
    resumo = insistencias([_perguntou(0, "regiao", "vagas"), _perguntou(1, "regiao", "vagas")])

    assert len(resumo.insistencias) == 2
    assert resumo.conversas_afetadas == 1


def test_campos_perguntados_exige_interrogacao():
    """A guarda que a TEC-210 apertou, e que esta funcao herdou inteira.

    Sem ela, o agente descrevendo um imovel contaria como tres perguntas.
    """
    assert campos_perguntados("Esse apartamento tem 2 quartos e 1 vaga de garagem") == set()
    assert campos_perguntados("Quantos quartos voce precisa?") == {"quartos"}


def test_marcadores_de_repergunta_usam_nomes_reais_da_extracao():
    """Trava o acordo entre a tabela de deteccao e os nomes que `Extracao`
    de fato tem -- os mesmos que `campos_a_gravar` (repositorio.py) grava e
    que `campos_a_marcar` subtrai deles.

    Sem este teste, um campo renomeado em `Extracao` (como
    `faixa_preco_max` -> `faixa_preco_max_centavos` na TEC-146) deixa
    `MARCADORES_DE_REPERGUNTA` com uma chave que nunca mais casa em
    `campos_a_marcar`. A marca de "perguntou e nao respondeu" para aquele
    campo fica impossivel, e nenhuma suite acusa: nada faz `assert False`,
    so um efeito que deixa de acontecer. Foi exatamente o defeito que a
    TEC-257 documentou ao extrair `campos_a_gravar`/`campos_a_marcar` para
    fora de copias divergentes -- e a mesma classe de erro que passou batido
    aqui, num lugar que aquela extracao nao cobria.
    """
    assert set(MARCADORES_DE_REPERGUNTA) <= CAMPOS_DA_EXTRACAO


def test_campos_perguntados_e_a_fonte_unica_dos_dois_proxies():
    """`_reperguntou` delega para ca desde a TEC-256.

    Duas copias da tabela de marcadores divergiriam, e a divergencia so
    apareceria na borda -- o defeito que `campos_a_gravar` e `_subcontagem` ja
    custaram a este projeto.
    """
    from evals.test_acuracia_de_intencao import _reperguntou

    texto = "Em qual bairro voce esta procurando? E quantos quartos?"

    assert campos_perguntados(texto) == {"regiao", "quartos"}
    # O proxy irmao e a intersecao com o que o estado ja sabe.
    assert _reperguntou(texto, ["regiao"]) == ["regiao"]
    assert _reperguntou(texto, ["vagas"]) == []
