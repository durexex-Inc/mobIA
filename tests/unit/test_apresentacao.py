"""A ficha e a legenda. TEC-162.

Basename distinto de tudo em `tests/integration/` -- colisao aborta a coleta
da suite inteira e nao aparece em execucao isolada.
"""

import uuid
from dataclasses import replace
from decimal import Decimal

from mobia.domain.agente.apresentacao import (
    MAX_CARACTERES_DA_LEGENDA,
    Ficha,
    custos_recorrentes,
    diferencial_de,
    legenda_de,
    reais_de,
    yield_bruto_anual,
)

# `replace` e nao `Ficha(**ficha.__dict__)`: `Ficha` e `slots=True` e nao tem
# `__dict__` -- a segunda forma levanta AttributeError.

COMPLETA = Ficha(
    id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=51646430,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial="churrasqueira e mobiliado",
    foto="https://exemplo.com/ap-1004-1.jpg",
)


def test_a_legenda_traz_os_oito_campos_da_rn_10_1() -> None:
    """RN-10.1: titulo, bairro, preco, quartos, vagas, area util, condominio
    e um diferencial em uma frase."""
    assert legenda_de(COMPLETA) == (
        "Apartamento em Lagoa da Conceicao\n"
        "Lagoa da Conceicao - R$ 516.464\n"
        "4 quartos - 2 vagas - 54 m2\n"
        "Condominio R$ 550\n"
        "Destaque: churrasqueira e mobiliado"
    )


def test_um_quarto_e_uma_vaga_nao_ficam_no_plural() -> None:
    """Fix wave da TEC-162 (Important). 129 dos 520 imoveis do seed tem
    vagas == 1 e 63 tem quartos == 1 -- "1 quartos - 1 vagas" saia errado no
    texto mais visivel que o lead recebe. 0 continua no plural de proposito
    (um TERRENO), e essa linha nao muda aqui."""
    legenda = legenda_de(replace(COMPLETA, quartos=1, vagas=1))
    assert "1 quarto - 1 vaga - 54 m2" in legenda


def test_os_centavos_sao_truncados_para_baixo_e_nunca_arredondados() -> None:
    """D11. Arredondar para cima cota ao lead um preco ACIMA do real, e e essa
    a direcao que vira reclamacao na visita. 51646430 centavos sao
    R$ 516.464,30 -- os 30 centavos caem, nao sobem o milhar."""
    assert reais_de(51646430) == "R$ 516.464"
    assert reais_de(51646499) == "R$ 516.464"
    assert reais_de(74900000) == "R$ 749.000"


def test_condominio_nulo_omite_a_linha_e_nao_esconde_o_imovel() -> None:
    """D13. Ausencia omite a linha; o imovel e apresentado de todo jeito."""
    legenda = legenda_de(replace(COMPLETA, condominio_centavos=None))
    assert "Condominio" not in legenda
    assert "Apartamento em Lagoa da Conceicao" in legenda
    assert "Destaque: churrasqueira e mobiliado" in legenda


def test_sem_caracteristica_nao_ha_linha_de_destaque() -> None:
    """117 dos 520 imoveis do seed nao tem caracteristica nenhuma -- isto nao
    e caso de borda inventado."""
    assert diferencial_de(()) is None
    assert "Destaque" not in legenda_de(replace(COMPLETA, diferencial=None))


def test_o_destaque_leva_as_duas_primeiras_na_ordem_do_catalogo() -> None:
    """Ordem armazenada e nao ranking: quem quiser priorizar muda o CSV."""
    assert diferencial_de(("churrasqueira", "mobiliado", "piscina", "sacada")) == (
        "churrasqueira e mobiliado"
    )
    assert diferencial_de(("piscina",)) == "piscina"


def test_o_prefixo_entra_antes_da_ficha_separado_por_linha_em_branco() -> None:
    """D5: a prosa do modelo vira prefixo da legenda do PRIMEIRO imovel."""
    legenda = legenda_de(COMPLETA, prefixo="Achei tres opcoes que encaixam.")
    assert legenda.startswith("Achei tres opcoes que encaixam.\n\n")
    assert legenda.endswith("Destaque: churrasqueira e mobiliado")


def test_o_teto_de_600_corta_a_prosa_e_nunca_a_ficha() -> None:
    """D14. A ficha e o conteudo que a RN-10.1 exige; a prosa e ornamento.

    O teto e o da RN-04.2, o mesmo numero de
    `evals/metricas.MAX_CARACTERES_DA_RESPOSTA` -- e este e o primeiro lugar
    de `src/` que o respeita por construcao.
    """
    ficha_inteira = legenda_de(COMPLETA)
    legenda = legenda_de(COMPLETA, prefixo="palavra " * 200)

    assert len(legenda) <= MAX_CARACTERES_DA_LEGENDA
    assert legenda.endswith(ficha_inteira)
    assert "..." in legenda


def test_prosa_que_nao_cabe_de_jeito_nenhum_sai_de_cena() -> None:
    """Se nem a reticencia couber, a prosa some inteira -- a ficha nao cede."""
    gigante = Ficha(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        titulo="T" * 300,
        bairro="B" * 200,
        preco_centavos=51646430,
        quartos=4,
        vagas=2,
        area_util_m2=54,
        condominio_centavos=55000,
        diferencial="churrasqueira e mobiliado",
        foto=None,
    )
    legenda = legenda_de(gigante, prefixo="Achei tres opcoes que encaixam.")

    assert legenda == legenda_de(gigante)
    assert not legenda.startswith("Achei")


def test_o_yield_do_gherkin_sai_com_uma_casa_e_zero_a_direita() -> None:
    """Cenario 1 da TEC-154: R$ 500.000 com aluguel de R$ 2.500 dao 6,0% ao ano.

    O zero a direita nao e enfeite: `6%` e `6,0%` dizem coisas diferentes
    sobre precisao.
    """
    assert yield_bruto_anual(250000, 50000000) == Decimal("6.0")


def test_o_yield_trunca_para_baixo_e_nunca_arredonda() -> None:
    """D4: arredondar para cima promete retorno acima do real.

    8760,04 * 12 / 2417514,29 = 4,3479...%, e o que sai e 4,3 -- nao 4,4.
    Sao os valores da linha TE-1007 do seed.
    """
    assert yield_bruto_anual(876004, 241751429) == Decimal("4.3")


def test_sem_aluguel_nao_ha_yield() -> None:
    assert yield_bruto_anual(None, 50000000) is None


def test_sem_preco_de_venda_nao_ha_yield() -> None:
    """Imovel so de aluguel: a RN-07.3 define o yield sobre o preco de venda."""
    assert yield_bruto_anual(250000, None) is None


def test_preco_de_venda_zero_nao_levanta_divisao_por_zero() -> None:
    """Nao ha linha assim no catalogo hoje (`ck_imoveis_ao_menos_um_preco` nao
    proibe zero, so NULL), e um ZeroDivisionError aqui derrubaria a
    apresentacao inteira por causa de um imovel."""
    assert yield_bruto_anual(250000, 0) is None


def test_os_custos_recorrentes_somam_condominio_e_iptu() -> None:
    assert custos_recorrentes(184400, 77100) == 261500


def test_um_custo_ausente_nao_zera_o_outro() -> None:
    """Ausente e zero sao coisas diferentes: somar so o que existe e o que
    mantem a linha verdadeira."""
    assert custos_recorrentes(184400, None) == 184400
    assert custos_recorrentes(None, 77100) == 77100


def test_sem_condominio_e_sem_iptu_nao_ha_linha_de_custos() -> None:
    assert custos_recorrentes(None, None) is None
