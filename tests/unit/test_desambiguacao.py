"""As duas decisoes do TEC-135, sem banco e sem modelo.

O cenario de aceite "confianca exatamente 0,6 nao desambigua" mora aqui e nao
num teste de integracao: e uma comparacao de borda, e o resto do turno nao
acrescenta nada a prova.
"""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from mobia.domain.agente.desambiguacao import deve_desambiguar, intencao_efetiva
from mobia.domain.agente.schemas import LIMIAR_DE_DESAMBIGUACAO, Intencao

JA_PERGUNTOU = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def test_confianca_no_limiar_exato_nao_desambigua() -> None:
    """Criterio de aceite: 0,6 e fechado por cima."""
    assert deve_desambiguar(Decimal("0.6"), None) is False


def test_logo_abaixo_do_limiar_desambigua() -> None:
    assert deve_desambiguar(Decimal("0.59"), None) is True


def test_marcador_preenchido_impede_a_segunda_pergunta() -> None:
    """Ambiguidade persistente nao vira insistencia."""
    assert deve_desambiguar(Decimal("0.45"), JA_PERGUNTOU) is False


def test_confianca_alta_nao_desambigua_com_ou_sem_marcador() -> None:
    assert deve_desambiguar(Decimal("0.91"), None) is False
    assert deve_desambiguar(Decimal("0.91"), JA_PERGUNTOU) is False


def test_intencao_abaixo_do_limiar_e_indefinida() -> None:
    """O palpite existe na tabela, mas ninguem roteia por ele."""
    assert intencao_efetiva(Intencao.COMPRA, Decimal("0.45")) is Intencao.INDEFINIDA


def test_intencao_no_limiar_exato_e_preservada() -> None:
    assert intencao_efetiva(Intencao.COMPRA, LIMIAR_DE_DESAMBIGUACAO) is Intencao.COMPRA


def test_intencao_confiante_passa_intacta() -> None:
    assert intencao_efetiva(Intencao.ALUGUEL, Decimal("0.91")) is Intencao.ALUGUEL


def test_o_limiar_continua_em_0_6_por_medicao() -> None:
    """O numero saiu do SRS sem calibragem, e a TEC-235 o mediu.

    Fica como teste, e nao so como comentario, porque mexer neste valor e
    mudanca de comportamento de producao em todo turno: quem baixar o limiar
    reprova aqui e vai ler o porque antes de seguir.

    O que a medicao diz, em seis execucoes: o rebaixamento **nunca** salvou um
    erro. E o custo dele -- acerto virando INDEFINIDA -- era de 4 a 6 turnos
    em 27/08/2026 e caiu a **zero** nas quatro execucoes de 30/08, sem que
    ninguem tocasse no limiar; trocou o modelo e cresceu o prompt. Baixa-lo
    hoje compra beneficio medido de zero.

    Ver o comentario de `LIMIAR_DE_DESAMBIGUACAO`, que carrega os numeros.
    """
    assert LIMIAR_DE_DESAMBIGUACAO == Decimal("0.6")


def test_nao_ha_um_segundo_limiar_de_confianca() -> None:
    """O `0,8` que dois comentarios citavam nunca governou nada.

    A TEC-235 varreu: a unica comparacao de confianca em `src/` e contra
    `LIMIAR_DE_DESAMBIGUACAO`. O teste existe para que um segundo limiar so
    entre nomeado -- um numero solto num `if` e exatamente como o `0,6`
    comecou, e foram tres cards ate ele virar medicao.
    """
    agente = Path(__file__).resolve().parents[2] / "src" / "mobia" / "domain" / "agente"
    for arquivo in agente.glob("*.py"):
        codigo = "\n".join(
            linha
            for linha in arquivo.read_text(encoding="utf-8").splitlines()
            if not linha.lstrip().startswith("#")
        )
        assert "0.8" not in codigo, f"{arquivo.name}: limiar solto de 0.8 fora de comentario"
