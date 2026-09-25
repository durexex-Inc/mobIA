"""O vocabulario do handoff: gatilho, etiqueta, prioridade.

Nao toca banco. Ver o conftest raiz: `tests/unit/` sai cedo de `banco_limpo`.
"""

from mobia.domain.handoff.vocabulario import ETIQUETA_DE, PRIORIDADE_DE, Gatilho, Prioridade


def test_todo_gatilho_tem_etiqueta_e_prioridade() -> None:
    """Os dois mapas cobrem o enum inteiro.

    Um gatilho sem etiqueta so falharia em producao, no instante do handoff.
    AGENDAMENTO_CONFIRMADO e o unico gatilho ainda sem chamador de
    `registrar_handoff` (a TEC-170 decidiu nao abrir handoff para ele -- ver o
    docstring de `Gatilho`); a etiqueta e a prioridade dele sao usadas no
    e-mail ao corretor e conferidas tambem em
    `tests/unit/test_mensagens_de_confirmacao.py`.
    """
    for gatilho in Gatilho:
        assert gatilho in ETIQUETA_DE
        assert gatilho in PRIORIDADE_DE


def test_as_etiquetas_do_gherkin_da_card() -> None:
    assert ETIQUETA_DE[Gatilho.LEAD_QUENTE] == "lead-quente"
    assert ETIQUETA_DE[Gatilho.PEDIDO_DE_HUMANO] == "pedido-humano"
    assert ETIQUETA_DE[Gatilho.VENDA_IMOVEL] == "venda-imovel"
    assert ETIQUETA_DE[Gatilho.LIMITE_DE_PERGUNTAS] == "qualificacao-parcial"


def test_so_o_pedido_de_humano_nasce_alta() -> None:
    """RN-16.1: pedido explicito alto, os demais normais."""
    altos = [g for g in Gatilho if PRIORIDADE_DE[g] is Prioridade.ALTA]
    assert altos == [Gatilho.PEDIDO_DE_HUMANO]


def test_as_etiquetas_cabem_na_coluna() -> None:
    """`etiqueta` e String(32). Estourar so apareceria no INSERT."""
    assert all(len(e) <= 32 for e in ETIQUETA_DE.values())
    assert all(len(g.value) <= 32 for g in Gatilho)
