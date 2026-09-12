import pytest

from mobia.domain.handoff.resumo import (
    LIMITE_DE_CARACTERES,
    MARCADORES,
    ResumoDeHandoffInvalido,
    validar,
)


def _resumo_valido(recheio: str = "texto do bloco") -> str:
    return "\n".join(f"{marcador}\n{recheio}" for marcador in MARCADORES)


def test_sao_seis_marcadores() -> None:
    assert len(MARCADORES) == 6


def test_validar_devolve_o_texto_quando_os_seis_blocos_estao_em_ordem() -> None:
    texto = _resumo_valido()
    assert validar(texto) == texto


def test_validar_recusa_quando_falta_um_bloco() -> None:
    texto = "\n".join(f"{m}\ntexto" for m in MARCADORES[:-1])

    with pytest.raises(ResumoDeHandoffInvalido, match="bloco ausente"):
        validar(texto)


def test_validar_recusa_quando_a_ordem_esta_trocada() -> None:
    trocados = (MARCADORES[1], MARCADORES[0], *MARCADORES[2:])
    texto = "\n".join(f"{m}\ntexto" for m in trocados)

    with pytest.raises(ResumoDeHandoffInvalido, match="fora de ordem"):
        validar(texto)


def test_validar_recusa_texto_vazio() -> None:
    with pytest.raises(ResumoDeHandoffInvalido, match="vazio"):
        validar("   \n  ")


def test_validar_recusa_acima_do_limite() -> None:
    excedente = _resumo_valido("x" * LIMITE_DE_CARACTERES)

    with pytest.raises(ResumoDeHandoffInvalido, match="acima do limite"):
        validar(excedente)


def test_o_limite_e_o_da_regra() -> None:
    # RN-15.2. Escrito aqui uma vez so; o resto do codigo importa a constante.
    assert LIMITE_DE_CARACTERES == 1500
