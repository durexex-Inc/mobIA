"""A CLI de seed: argumentos, codigo de saida e o relatorio no stdout.

TEC-156. Testa a casca, nao a importacao -- `_executar` e dublado. A logica de
verdade tem cobertura de integracao em tests/integration/test_catalogo_upsert.py.
"""

import pytest

from mobia.admin import seed_catalogo
from mobia.domain.catalogo.schemas import Rejeicao, Relatorio


@pytest.fixture
def sem_banco(monkeypatch: pytest.MonkeyPatch):
    """Substitui a rotina async por uma que devolve um relatorio pronto."""
    chamadas: list[dict] = []

    def instalar(relatorio: Relatorio) -> list[dict]:
        async def falso(*, arquivo, origem):
            chamadas.append({"arquivo": arquivo, "origem": origem})
            return relatorio

        monkeypatch.setattr(seed_catalogo, "_importar", falso)
        return chamadas

    return instalar


def test_usa_o_arquivo_padrao_quando_nenhum_e_passado(sem_banco, capsys):
    chamadas = sem_banco(Relatorio(processados=520, inseridos=520))
    assert seed_catalogo.main([]) == 0
    assert chamadas[0]["arquivo"] == seed_catalogo.ARQUIVO_PADRAO


def test_imprime_os_cinco_totais(sem_banco, capsys):
    sem_banco(Relatorio(processados=500, inseridos=497, atualizados=0, inalterados=0, rejeitados=3))
    seed_catalogo.main([])
    saida = capsys.readouterr().out
    for rotulo in ("processados", "inseridos", "atualizados", "inalterados", "rejeitados"):
        assert rotulo in saida


def test_imprime_linha_e_motivo_de_cada_rejeicao(sem_banco, capsys):
    sem_banco(
        Relatorio(
            processados=2,
            inseridos=1,
            rejeitados=1,
            erros=[Rejeicao(linha=12, motivo="preco_venda ausente")],
        )
    )
    seed_catalogo.main([])
    saida = capsys.readouterr().out
    assert "12" in saida
    assert "preco_venda ausente" in saida


def test_sai_com_zero_mesmo_havendo_rejeicoes(sem_banco):
    # O primeiro cenario Gherkin exige que 3 linhas ruins terminem "com
    # sucesso". Sair diferente de zero aqui reprovaria o criterio de aceite.
    sem_banco(Relatorio(processados=500, inseridos=497, rejeitados=3))
    assert seed_catalogo.main([]) == 0


def test_falhar_se_rejeitar_inverte_o_codigo_de_saida(sem_banco):
    sem_banco(Relatorio(processados=500, inseridos=497, rejeitados=3))
    assert seed_catalogo.main(["--falhar-se-rejeitar"]) == 1


def test_falhar_se_rejeitar_sai_zero_quando_nao_ha_rejeicao(sem_banco):
    sem_banco(Relatorio(processados=500, inseridos=500))
    assert seed_catalogo.main(["--falhar-se-rejeitar"]) == 0


def test_arquivo_inexistente_sai_com_erro(sem_banco, capsys):
    sem_banco(Relatorio())
    assert seed_catalogo.main(["--arquivo", "nao/existe.csv"]) == 2
    assert "nao/existe.csv" in capsys.readouterr().err
