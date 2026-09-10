"""A guarda anti-alucinacao sobre a prosa do modelo. TEC-161.

Basename distinto de tudo em `tests/integration/` -- o par de integracao
chama-se `test_citacao_no_turno.py`.
"""

from typing import Any

import pytest

from mobia.domain.agente.citacao import Divergencia, divergencias_de

SEM_FAIXA: tuple[int | None, int | None] = (None, None)


def _candidato(codigo: str, preco: int) -> dict[str, Any]:
    """O que `_candidato_serializavel` devolve hoje, reduzido ao que importa."""
    return {
        "imovel_id": "0f9d1a1e-0000-4000-8000-000000000001",
        "codigo": codigo,
        "titulo": f"Apartamento {codigo}",
        "bairro": "Lagoa da Conceicao",
        "preco_centavos": preco,
        "quartos": 4,
        "vagas": 2,
        "area_util_m2": 54,
    }


def test_prosa_sem_cifra_nem_codigo_passa() -> None:
    assert (
        divergencias_de(
            "Achei tres opcoes que encaixam no que voce falou.",
            candidatos=[_candidato("AP-1004", 51_646_430)],
            faixa=SEM_FAIXA,
        )
        == ()
    )


@pytest.mark.parametrize("citado", ["R$ 516.464", "516 mil", "500 mil", "R$ 470 mil"])
def test_preco_dentro_da_tolerancia_passa(citado: str) -> None:
    """D4: o modelo le 51646430 e escreve o numero arredondado do jeito dele.

    Igualdade exata reprovaria prosa correta em quase todo turno. 470 mil e o
    limite inferior dos 10% de 516.464 -- 464.817 -- por pouco.
    """
    assert (
        divergencias_de(
            f"Tenho um por {citado}.",
            candidatos=[_candidato("AP-1004", 51_646_430)],
            faixa=SEM_FAIXA,
        )
        == ()
    )


def test_preco_fora_da_tolerancia_bloqueia() -> None:
    divergencias = divergencias_de(
        "Tenho um por R$ 700 mil.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    )
    assert divergencias == (Divergencia(tipo="preco", citado="R$ 700.000"),)


def test_o_limite_da_tolerancia_e_fechado_dos_dois_lados() -> None:
    """Exatamente 10% passa; um real alem nao.

    Sem este teste, trocar `<=` por `<` na comparacao passa nos outros.
    """
    candidatos = [_candidato("AP-1004", 100_000_000)]
    assert divergencias_de("R$ 1.100.000", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de("R$ 900.000", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de("R$ 1.100.001", candidatos=candidatos, faixa=SEM_FAIXA) != ()


def test_basta_um_candidato_casar() -> None:
    """A prosa fala de um imovel entre varios; nao ha como saber qual."""
    assert (
        divergencias_de(
            "Tenho um por R$ 700 mil.",
            candidatos=[_candidato("AP-1", 51_646_430), _candidato("AP-2", 70_000_000)],
            faixa=SEM_FAIXA,
        )
        == ()
    )


def test_a_faixa_declarada_pelo_lead_e_valor_legitimo() -> None:
    """D5: o modelo ecoando o orcamento do lead nao e alucinacao.

    Sem esta valvula, "entendi, ate R$ 600 mil" bloqueia num turno de
    qualificacao pura -- que e o turno mais comum da conversa.
    """
    assert (
        divergencias_de(
            "Entendi, ate R$ 600 mil.",
            candidatos=[],
            faixa=(None, 60_000_000),
        )
        == ()
    )


def test_sem_candidato_e_sem_faixa_qualquer_cifra_bloqueia() -> None:
    """D7: o caso RT-01 mais puro -- o modelo nao buscou e citou preco."""
    assert divergencias_de(
        "Tenho um otimo por R$ 600 mil.",
        candidatos=[],
        faixa=SEM_FAIXA,
    ) == (Divergencia(tipo="preco", citado="R$ 600.000"),)


def test_codigo_de_candidato_passa_e_codigo_inventado_bloqueia() -> None:
    candidatos = [_candidato("AP-1004", 51_646_430)]
    assert divergencias_de("O AP-1004 te atende.", candidatos=candidatos, faixa=SEM_FAIXA) == ()
    assert divergencias_de("O AP-9999 te atende.", candidatos=candidatos, faixa=SEM_FAIXA) == (
        Divergencia(tipo="codigo", citado="AP-9999"),
    )


def test_codigo_de_outro_formato_nao_e_detectado() -> None:
    """D6, a lacuna travada como teste.

    A coluna e String(20) sem constraint de formato. Este teste existe para
    que quem mudar o formato do codigo do catalogo veja aqui, e nao em
    producao, que a guarda deixou de enxerga-lo.
    """
    assert (
        divergencias_de(
            "O imovel 1004/AP te atende.",
            candidatos=[_candidato("AP-1004", 51_646_430)],
            faixa=SEM_FAIXA,
        )
        == ()
    )


def test_preco_e_codigo_divergentes_saem_juntos() -> None:
    """Uma passada, todas as divergencias -- quem investiga quer as duas."""
    divergencias = divergencias_de(
        "O AP-9999 sai por R$ 900 mil.",
        candidatos=[_candidato("AP-1004", 51_646_430)],
        faixa=SEM_FAIXA,
    )
    assert set(divergencias) == {
        Divergencia(tipo="preco", citado="R$ 900.000"),
        Divergencia(tipo="codigo", citado="AP-9999"),
    }


def test_candidato_com_preco_zero_nao_quebra_a_conta() -> None:
    """Divisao por zero seria excecao dentro da guarda, e guarda que levanta
    derruba o turno inteiro -- o oposto do que ela existe para fazer."""
    assert (
        divergencias_de("Sai por R$ 600 mil.", candidatos=[_candidato("AP-1", 0)], faixa=SEM_FAIXA)
        != ()
    )
