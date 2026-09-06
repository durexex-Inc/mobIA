"""Os cinco totais do relatorio, e a identidade que os fecha.

TEC-156, RN-08.5 e a emenda E-01 dela. O cenario 3 do Gherkin reimporta 500
imoveis com 10 precos alterados e exige que 10 aparecam como atualizados --
nao 500. Isso obriga `atualizados` a significar "mudou de valor", e obriga um
quinto total para as 490 que casaram e nao mudaram. Ver D3 do desenho.
"""

from mobia.domain.catalogo.schemas import Rejeicao, Relatorio


def test_relatorio_comeca_zerado():
    r = Relatorio()
    assert (r.processados, r.inseridos, r.atualizados, r.inalterados, r.rejeitados) == (
        0,
        0,
        0,
        0,
        0,
    )
    assert r.erros == []


def test_os_quatro_totais_do_srs_continuam_existindo():
    # A card e o SRS cobram estes quatro nomes. O quinto os acompanha, nao os
    # substitui -- se algum destes sumir, o contrato publicado quebrou.
    r = Relatorio()
    for nome in ("processados", "inseridos", "atualizados", "rejeitados"):
        assert hasattr(r, nome)


def test_cenario_3_do_gherkin_fecha():
    """500 reimportados, 10 precos alterados: 0 novos, 10 atualizados, 490 iguais."""
    r = Relatorio(processados=500, inseridos=0, atualizados=10, inalterados=490, rejeitados=0)
    assert r.fecha()


def test_cenario_1_do_gherkin_fecha():
    """500 linhas, 3 invalidas: 497 gravados e 3 rejeitados."""
    r = Relatorio(
        processados=500,
        inseridos=497,
        atualizados=0,
        inalterados=0,
        rejeitados=3,
        erros=[Rejeicao(linha=12, motivo="preco_venda ausente")],
    )
    assert r.fecha()


def test_total_que_nao_fecha_e_detectado():
    # Sem o quinto total, este era exatamente o estado do cenario 3: quatro
    # numeros que nao somam e 490 linhas sem explicacao.
    r = Relatorio(processados=500, inseridos=0, atualizados=10, inalterados=0, rejeitados=0)
    assert not r.fecha()


def test_registrar_rejeicao_incrementa_os_dois_contadores():
    r = Relatorio()
    r.registrar_rejeicao(Rejeicao(linha=7, motivo="tipo invalido: 'apto'"))
    assert r.rejeitados == 1
    assert r.processados == 1
    assert r.erros[0].linha == 7
