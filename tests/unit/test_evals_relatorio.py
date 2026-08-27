from decimal import Decimal

from mobia.domain.agente.schemas import Intencao
from mobia.evals.metricas import (
    TETO_DE_CONVERSAS_ABANDONADAS,
    Classificacao,
    FalhaDeInfraestrutura,
    ResumoDeConfianca,
    acuracia_de_intencao,
    sem_mecanismo,
)
from mobia.evals.relatorio import render

CONFIANTE = Decimal("0.90")
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


def test_relatorio_aponta_qual_metrica_regrediu() -> None:
    """O criterio de aceite do card exige que o relatorio diga qual metrica
    caiu, nao apenas que algo caiu."""
    metricas = [acuracia_de_intencao([classificacao(Intencao.COMPRA, Intencao.ALUGUEL)])]

    texto = render(metricas, {})

    assert "acuracia de intencao" in texto
    assert "VERMELHO" in texto


def test_as_tres_metricas_sem_mecanismo_aparecem_declaradas() -> None:
    """Elas tem de ser visiveis em toda execucao. Uma metrica ausente do
    relatorio vira uma metrica esquecida."""
    metricas = [
        sem_mecanismo("precisao de extracao", "TEC-145 nao existe"),
        sem_mecanismo("taxa de alucinacao", "bloqueada pela TEC-161"),
        sem_mecanismo("aderencia ao tom", "TEC-140 nao existe"),
    ]

    texto = render(metricas, {})

    assert texto.count("SEM_MECANISMO") == 3
    assert "TEC-161" in texto


def test_matriz_mostra_para_onde_a_intencao_escorreu() -> None:
    confusao = {Intencao.INVESTIMENTO: {Intencao.COMPRA: 7, Intencao.INVESTIMENTO: 2}}

    texto = render([], confusao)

    assert "INVESTIMENTO" in texto
    assert "COMPRA" in texto
    assert "7" in texto


def test_matriz_ordena_erros_por_valor_quando_empata_em_contagem() -> None:
    """Quando duas obtida tem a mesma contagem, deve ordenar deterministica
    por .value do enum, nao pela ordem de insercao do dict. Testa com insercao
    invertida (COMPRA antes de ALUGUEL) para pegar o sort sem desempate."""
    confusao = {
        Intencao.INVESTIMENTO: {
            Intencao.COMPRA: 3,
            Intencao.ALUGUEL: 3,
        }
    }

    texto = render([], confusao)

    linhas = texto.split("\n")
    idx_aluguel = next(i for i, linha in enumerate(linhas) if "ALUGUEL" in linha)
    idx_compra = next(i for i, linha in enumerate(linhas) if "COMPRA" in linha)

    assert idx_aluguel < idx_compra, "ALUGUEL deve aparecer antes de COMPRA (ordem alfabetica)"


def test_relatorio_traz_a_contagem_de_turnos_abaixo_do_limiar() -> None:
    """Sem esta secao, recalibrar o limiar exigiria outra execucao paga: e o
    unico lugar onde as contagens de confianca saem da execucao."""
    resumo = ResumoDeConfianca(
        turnos=100, abaixo_do_limiar=21, acertos_rebaixados=18, acertos_recuperados=3
    )

    texto = render([], {}, confianca=resumo)

    assert "## Confianca" in texto
    assert "21/100" in texto
    assert "acertos rebaixados para INDEFINIDA: 18" in texto
    assert "erros que o rebaixamento acertou: 3" in texto


def test_relatorio_nomeia_cada_turno_errado() -> None:
    """O agregado nao da para investigar. A matriz diz que INVESTIMENTO virou
    COMPRA sete vezes e nao diz quais sete; descobrir isso sem estas linhas
    custa outra execucao paga, porque o relatorio vive em log efemero de CI.
    """
    erradas = [
        classificacao(
            Intencao.INVESTIMENTO,
            Intencao.COMPRA,
            conversa_id="investimento-04",
            indice=2,
            confianca=Decimal("0.91"),
        ),
    ]

    texto = render([], {}, erradas=erradas)

    assert "## Classificacoes erradas" in texto
    assert "- investimento-04[2]: INVESTIMENTO -> COMPRA (0.91)" in texto


def test_relatorio_distingue_o_acerto_rebaixado_do_erro_de_classificacao() -> None:
    """As duas linhas pedem acoes diferentes: uma e calibragem da confianca,
    a outra e o classificador errando. E sem a marca a primeira pareceria bug
    do relatorio, porque mostra `esperada -> obtida` iguais."""
    rebaixada = classificacao(
        Intencao.COMPRA, Intencao.COMPRA, conversa_id="compra-07", indice=1, confianca=INSEGURA
    )
    errada = classificacao(
        Intencao.ALUGUEL, Intencao.COMPRA, conversa_id="aluguel-02", indice=0, confianca=CONFIANTE
    )

    texto = render([], {}, erradas=[rebaixada, errada])

    assert "- compra-07[1]: COMPRA -> COMPRA (0.50)  <-- certa, rebaixada para INDEFINIDA" in texto
    assert "- aluguel-02[0]: ALUGUEL -> COMPRA (0.90)" in texto
    assert "aluguel-02[0]: ALUGUEL -> COMPRA (0.90)  <--" not in texto


def test_relatorio_marca_o_erro_que_o_rebaixamento_acerta() -> None:
    """Explica a acuracia efetiva ficar acima da crua. Sem a marca, esta
    linha na lista de erradas contradiz a metrica logo acima dela."""
    recuperada = classificacao(
        Intencao.INDEFINIDA, Intencao.COMPRA, conversa_id="borda-evasivo-01", confianca=INSEGURA
    )

    texto = render([], {}, erradas=[recuperada])

    assert "<-- errada, mas o rebaixamento acerta o rotulo" in texto


def test_relatorio_sem_erradas_omite_a_secao() -> None:
    """Execucao sem erro nenhum nao ganha um cabecalho vazio."""
    texto = render([], {})

    assert "## Classificacoes erradas" not in texto


def test_relatorio_sem_resumo_de_confianca_omite_a_secao() -> None:
    """Uma secao de confianca com zeros mentiria: zero turnos abaixo do
    limiar e um resultado, "nao foi medido" e outro."""
    texto = render([], {})

    assert "## Confianca" not in texto


def test_relatorio_separa_falha_de_infraestrutura_de_erro_de_classificacao() -> None:
    """Vermelho por 429 e vermelho por regressao pedem acoes opostas -- re-rodar
    contra investigar. A conversa que a rede levou tem de aparecer nomeada, e
    fora da lista de classificacoes erradas: nenhum turno dela foi medido."""
    falhas = [FalhaDeInfraestrutura(conversa_id="compra-12", indice=1, erro="APIStatusError")]
    erradas = [classificacao(Intencao.ALUGUEL, Intencao.COMPRA, conversa_id="aluguel-02")]

    texto = render([], {}, erradas=erradas, infraestrutura=falhas)

    assert "## Falhas de infraestrutura" in texto
    assert "- compra-12[1]: APIStatusError" in texto
    assert "Nao sao erro de classificacao" in texto
    depois_das_erradas = texto.split("## Classificacoes erradas")[1]
    assert "compra-12" not in depois_das_erradas


def test_relatorio_anuncia_o_teto_junto_da_contagem_de_abandono() -> None:
    """Sem o teto ao lado, "3 conversas abandonadas" nao diz se a execucao
    ainda vale -- e essa e a unica pergunta que o leitor tem ali."""
    falhas = [
        FalhaDeInfraestrutura(conversa_id=f"compra-{i}", indice=0, erro="APITimeoutError")
        for i in range(3)
    ]

    texto = render([], {}, infraestrutura=falhas)

    assert f"3 conversa(s) abandonada(s), teto {TETO_DE_CONVERSAS_ABANDONADAS}." in texto


def test_a_secao_de_infraestrutura_vem_antes_das_que_dependem_das_metricas() -> None:
    """Ela muda como se le o resto do relatorio, entao precede o resto. Quem
    abre o log de CI tem de saber que a execucao perdeu conversas antes de
    interpretar os numeros que vem depois."""
    texto = render(
        [],
        {Intencao.COMPRA: {Intencao.ALUGUEL: 1}},
        confianca=ResumoDeConfianca(
            turnos=1, abaixo_do_limiar=0, acertos_rebaixados=0, acertos_recuperados=0
        ),
        erradas=[classificacao(Intencao.ALUGUEL, Intencao.COMPRA)],
        infraestrutura=[FalhaDeInfraestrutura("compra-12", 1, "APIStatusError")],
    )

    assert texto.index("## Falhas de infraestrutura") < texto.index("## Confianca")
    assert texto.index("## Confianca") < texto.index("## Classificacoes erradas")
    assert texto.index("## Classificacoes erradas") < texto.index("## Matriz de confusao")


def test_relatorio_sem_falha_de_infraestrutura_omite_a_secao() -> None:
    """Execucao limpa nao ganha um cabecalho que sugere que algo caiu."""
    texto = render([], {})

    assert "## Falhas de infraestrutura" not in texto
