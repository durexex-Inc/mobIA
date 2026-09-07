"""A CLI de seed: argumentos, codigo de saida e o relatorio no stdout.

TEC-156. Testa a casca, nao a importacao -- `_importar` e dublado. A logica de
verdade tem cobertura de integracao em tests/integration/test_catalogo_upsert.py.
"""

from pathlib import Path

import pytest

from mobia.admin import seed_catalogo
from mobia.domain.catalogo.enums import StatusImportacao
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
    # str(Path(...)) e nao o literal "nao/existe.csv": no Windows a mensagem
    # usa "\", que e a mesma convencao do --arquivo-padrao no --help.
    assert str(Path("nao/existe.csv")) in capsys.readouterr().err


def test_importacao_que_falhou_sai_com_um_sem_a_flag(sem_banco):
    """FALHOU nao e rejeicao: sai diferente de zero mesmo sem a flag.

    Era este o buraco: com o desfecho vivendo so na linha do banco, o objeto
    devolvido num arquivo sem a coluna `codigo` era zero em tudo e `erros`
    vazia -- indistinguivel de uma importacao limpa sobre arquivo vazio --, e
    a CLI saia com 0 sobre um catalogo que nao entrou.
    """
    sem_banco(
        Relatorio(
            status=StatusImportacao.FALHOU,
            erros=[Rejeicao(linha=0, motivo="cabecalho sem coluna obrigatoria: codigo")],
        )
    )
    assert seed_catalogo.main([]) == 1


def test_importacao_que_falhou_sai_com_um_tambem_com_a_flag(sem_banco):
    sem_banco(Relatorio(status=StatusImportacao.FALHOU, erros=[Rejeicao(linha=0, motivo="x")]))
    assert seed_catalogo.main(["--falhar-se-rejeitar"]) == 1


def test_imprime_o_status_e_o_motivo_da_falha(sem_banco, capsys):
    sem_banco(
        Relatorio(
            status=StatusImportacao.FALHOU,
            erros=[Rejeicao(linha=0, motivo="cabecalho sem coluna obrigatoria: codigo")],
        )
    )
    seed_catalogo.main([])
    saida = capsys.readouterr().out
    assert "FALHOU" in saida
    assert "cabecalho sem coluna obrigatoria: codigo" in saida
    # Linha 0 nao existe no arquivo: imprimi-la como rejeicao mandaria o admin
    # procurar uma linha que nao ha.
    assert "linha 0" not in saida


def test_concluido_imprime_o_status(sem_banco, capsys):
    sem_banco(Relatorio(status=StatusImportacao.CONCLUIDO, processados=1, inseridos=1))
    assert seed_catalogo.main([]) == 0
    assert "CONCLUIDO" in capsys.readouterr().out
