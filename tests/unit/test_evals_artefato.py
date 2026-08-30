"""O relatorio de uma execucao paga tem de sobrar em disco.

A execucao de 28/08/2026 rodou, custou dinheiro e produziu 29 discrepancias.
O percentual, a faixa e o relatorio nao existem em lugar nenhum: sairam num
terminal que fechou. A TEC-247 fechou essa lacuna gravando o artefato, e
estes testes guardam as tres propriedades sem as quais ela reabre --
o arquivo sai, ele carrega as condicoes de validade, e o disco nao derruba a
medicao.
"""

import os
from decimal import Decimal
from pathlib import Path

import pytest

from evals.test_acuracia_de_intencao import _condicoes_da_execucao, _destino_do_relatorio
from mobia.domain.agente.schemas import Intencao
from mobia.evals.corpus import ConversaAnotada, TurnoAnotado
from mobia.evals.metricas import (
    PISO_DE_TURNOS,
    PISO_DE_TURNOS_ANOTADOS,
    PISO_DE_TURNOS_NEGATIVOS,
    Classificacao,
    ExtracaoObservada,
    FalhaDeInfraestrutura,
)
from mobia.evals.relatorio import DIRETORIO_DE_RELATORIOS, preservar


def _conversa(id_: str, turnos: int) -> ConversaAnotada:
    return ConversaAnotada(
        id=id_,
        descricao="",
        turnos=[TurnoAnotado(lead="oi", intencao=Intencao.COMPRA) for _ in range(turnos)],
    )


def _classificacao(indice: int) -> Classificacao:
    return Classificacao(
        conversa_id="compra-01",
        indice=indice,
        esperada=Intencao.COMPRA,
        obtida=Intencao.COMPRA,
        confianca=Decimal("0.9"),
    )


def _observada(esperado: dict[str, object]) -> ExtracaoObservada:
    return ExtracaoObservada(conversa_id="compra-01", indice=0, esperado=esperado, obtido={})


def test_preservar_grava_o_texto_criando_o_diretorio(tmp_path: Path) -> None:
    """O diretorio nao existe na primeira execucao de um clone limpo, e falhar
    ali seria perder o artefato por um `mkdir` que ninguem rodou."""
    destino = tmp_path / "relatorios" / "2026-08-30.md"
    assert preservar("# medicao\n", destino) == destino
    assert destino.read_text(encoding="utf-8") == "# medicao\n"


def test_preservar_sobrescreve_execucao_do_mesmo_dia(tmp_path: Path) -> None:
    """Duas execucoes no mesmo dia caem no mesmo nome default. A segunda vale:
    e a mais recente contra o mesmo corpus, e guardar as duas exigiria um nome
    que o runner nao tem como escolher sozinho."""
    destino = tmp_path / "2026-08-30.md"
    preservar("primeira\n", destino)
    preservar("segunda\n", destino)
    assert destino.read_text(encoding="utf-8") == "segunda\n"


def test_destino_default_fica_dentro_do_repositorio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ancorado no arquivo, nao no cwd: um `pytest evals` disparado de outro
    diretorio gravaria o artefato pago fora da arvore, onde ninguem o
    commitaria."""
    monkeypatch.delenv("RELATORIO_DE_EVAL", raising=False)
    monkeypatch.chdir(Path(__file__).parent)
    destino = _destino_do_relatorio()
    assert destino.is_absolute()
    assert destino.parent.name == DIRETORIO_DE_RELATORIOS.name
    assert destino.suffix == ".md"


def test_destino_respeita_a_variavel_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    """O disparo manual precisa nomear o arquivo: o commit do corpus nao cabe
    numa data."""
    monkeypatch.setenv("RELATORIO_DE_EVAL", os.path.join("outro", "lugar.md"))
    assert _destino_do_relatorio() == Path("outro") / "lugar.md"


def test_condicoes_trazem_a_folga_de_cada_piso() -> None:
    """Uma execucao que rocou um piso vale menos que uma folgada, e o
    relatorio sozinho nao diz qual das duas foi."""
    linhas = _condicoes_da_execucao(
        [_conversa("compra-01", 3)],
        [_classificacao(i) for i in range(PISO_DE_TURNOS + 9)],
        [_observada({"quartos": 2}) for _ in range(PISO_DE_TURNOS_ANOTADOS + 2)]
        + [_observada({}) for _ in range(PISO_DE_TURNOS_NEGATIVOS + 2)],
        [],
    )
    texto = "\n".join(linhas)
    assert f"turnos medidos: {PISO_DE_TURNOS + 9}/{PISO_DE_TURNOS}, folga de 9" in texto
    assert (
        f"positivos: {PISO_DE_TURNOS_ANOTADOS + 2}/{PISO_DE_TURNOS_ANOTADOS}, folga de 2" in texto
    )
    assert (
        f"negativos: {PISO_DE_TURNOS_NEGATIVOS + 2}/{PISO_DE_TURNOS_NEGATIVOS}, folga de 2" in texto
    )


def test_condicoes_registram_zero_abandono_explicitamente() -> None:
    """`_secao_de_infraestrutura` so imprime quando houve falha. Sem esta
    linha, "nenhuma conversa abandonada" e indistinguivel de "ninguem
    contou"."""
    linhas = _condicoes_da_execucao([_conversa("compra-01", 3)], [_classificacao(0)], [], [])
    assert "conversas abandonadas por infraestrutura: 0" in "\n".join(linhas)


def test_condicoes_contam_as_conversas_abandonadas() -> None:
    linhas = _condicoes_da_execucao(
        [_conversa("compra-01", 3)],
        [_classificacao(0)],
        [],
        [FalhaDeInfraestrutura(conversa_id="compra-02", indice=1, erro="RateLimitError")],
    )
    assert "conversas abandonadas por infraestrutura: 1" in "\n".join(linhas)


def test_folga_negativa_aparece_com_sinal() -> None:
    """A linha tem de acusar sozinha que a amostra nao sustenta o numero. Sem
    o sinal, "45/53" pede que o leitor faca a conta -- e a mensagem existe
    justamente para quem esta lendo o baseline meses depois."""
    linhas = _condicoes_da_execucao(
        [_conversa("compra-01", 3)],
        [_classificacao(i) for i in range(PISO_DE_TURNOS - 4)],
        [],
        [],
    )
    assert f"turnos medidos: {PISO_DE_TURNOS - 4}/{PISO_DE_TURNOS}, folga de -4" in "\n".join(
        linhas
    )
