"""Testes de `mensagem.py`: qual novidade entra no followup, e como vira texto.

TEC-184, Task 4. Modulo puro, sem banco -- roda em tests/unit.
"""

import uuid

import pytest

from mobia.domain.agente.apresentacao import Ficha
from mobia.domain.followup.mensagem import (
    CONVITE_PARA_AGENDAR,
    QuedaDePreco,
    linha_da_queda,
    texto_do_followup,
)

FICHA = Ficha(
    id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
    titulo="Apartamento em Lagoa da Conceicao",
    bairro="Lagoa da Conceicao",
    preco_centavos=51646430,
    quartos=4,
    vagas=2,
    area_util_m2=54,
    condominio_centavos=55000,
    diferencial="churrasqueira e mobiliado",
    foto=None,
)

QUEDA = QuedaDePreco(
    imovel_id=FICHA.id,
    preco_antes_centavos=62_000_000,
    preco_agora_centavos=59_000_000,
)


def test_a_linha_da_queda_traz_os_dois_precos_truncados_para_baixo() -> None:
    """`reais_de` trunca dos dois lados, pela razao que ela ja documenta:
    arredondar para cima cota ao lead um preco acima do real."""
    assert linha_da_queda(QUEDA) == "De R$ 620.000 por R$ 590.000"


def test_a_queda_vence_o_imovel_novo() -> None:
    """D2: a queda e sobre algo em que o lead JA demonstrou interesse; um
    anuncio que ele nunca viu e aposta mais fraca."""
    texto = texto_do_followup(ficha=FICHA, queda=QUEDA)
    assert "De R$ 620.000 por R$ 590.000" in texto
    assert CONVITE_PARA_AGENDAR not in texto


def test_o_imovel_novo_vence_o_convite() -> None:
    texto = texto_do_followup(ficha=FICHA, queda=None)
    assert "Apartamento em Lagoa da Conceicao" in texto
    assert CONVITE_PARA_AGENDAR not in texto


def test_sem_novidade_sobra_o_convite() -> None:
    """Cenario 3 do Gherkin, e a razao de a mensagem vazia ser IMPOSSIVEL e
    nao bloqueada (D6): o convite sempre existe."""
    assert texto_do_followup(ficha=None, queda=None) == CONVITE_PARA_AGENDAR


def test_o_convite_nao_e_uma_saudacao_sem_conteudo() -> None:
    """A card proibe "oi, tudo bem?" solto. O convite tem de PEDIR algo."""
    assert "?" in CONVITE_PARA_AGENDAR
    assert "visita" in CONVITE_PARA_AGENDAR.lower()


def test_o_prefixo_do_modelo_entra_antes_e_cede_primeiro() -> None:
    """Mesma prioridade da apresentacao (D14 da TEC-162): corta-se a prosa,
    nunca o fato."""
    texto = texto_do_followup(ficha=FICHA, queda=None, prefixo="palavra " * 200)
    assert len(texto) <= 600
    assert "Apartamento em Lagoa da Conceicao" in texto
    assert "Condominio R$ 550" in texto
    # A prosa sobrevive truncada, e nao e descartada inteira: sem esta linha,
    # um `_com_prefixo` quebrado que jogasse o prefixo fora passaria nas tres
    # asserta acima do mesmo jeito, porque a legenda sozinha ja tem 147
    # caracteres, ja contem o titulo e ja contem o condominio. Mesmo risco que
    # `test_o_teto_de_600_corta_a_prosa_e_nunca_o_bloco_do_investidor` documenta
    # em `test_apresentacao.py`.
    assert texto.startswith("palavra palavra")
    assert "\n\n" in texto


def test_a_ficha_da_queda_e_a_do_imovel_que_caiu() -> None:
    """Passar uma ficha de OUTRO imovel junto com a queda seria mostrar o
    preco de um e a ficha de outro -- o lead nao tem como perceber."""
    outra = Ficha(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        titulo="Casa no Centro",
        bairro="Centro",
        preco_centavos=59_000_000,
        quartos=3,
        vagas=1,
        area_util_m2=90,
        condominio_centavos=None,
        diferencial=None,
        foto=None,
    )
    with pytest.raises(ValueError):
        texto_do_followup(ficha=outra, queda=QUEDA)


def test_tudo_que_sai_para_o_lead_e_ascii() -> None:
    """Acento aqui chega ao WhatsApp do lead."""
    for texto in (
        CONVITE_PARA_AGENDAR,
        linha_da_queda(QUEDA),
        texto_do_followup(ficha=FICHA, queda=None),
    ):
        assert texto.isascii(), texto
