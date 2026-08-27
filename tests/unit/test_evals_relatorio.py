from mobia.domain.agente.schemas import Intencao
from mobia.evals.metricas import Classificacao, acuracia_de_intencao, sem_mecanismo
from mobia.evals.relatorio import render


def test_relatorio_aponta_qual_metrica_regrediu() -> None:
    """O criterio de aceite do card exige que o relatorio diga qual metrica
    caiu, nao apenas que algo caiu."""
    metricas = [acuracia_de_intencao([Classificacao("c", 0, Intencao.COMPRA, Intencao.ALUGUEL)])]

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
