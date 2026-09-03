"""A regra da recusa de campo, sem banco.

TEC-148.
"""

import logging

from mobia.domain.context.repositorio import campos_a_recusar


def test_o_nome_do_orcamento_e_traduzido_para_a_forma_canonica():
    """O orcamento tem varios nomes neste repo, e o unico que o modelo pode
    dizer nao e coluna. `_marca_de` traduz, e e a mesma traducao que
    `campos_a_marcar` usa -- duas divergiriam."""
    assert campos_a_recusar(["faixa_preco_expressao"], []) == {"faixa_preco_max"}


def test_nome_fora_do_vocabulario_e_descartado_e_nao_adivinhado():
    """Recusa inventada faz o agente parar de perguntar um obrigatorio e
    `esta_qualificado` devolver False para sempre, em silencio. Descartar e o
    erro barato."""
    assert campos_a_recusar(["bairro_favorito"], []) == set()


def test_campo_preenchido_neste_turno_nao_entra_como_recusado():
    """Cenario 2 da card: valor vence recusa. Se o lead informou o campo, ele
    nao esta recusando o campo."""
    assert campos_a_recusar(["regiao"], ["regiao"]) == set()


def test_o_orcamento_preenchido_por_qualquer_extremo_cancela_a_recusa_dele():
    """ "a partir de 300 mil" preenche so o minimo, e responde a pergunta sobre
    orcamento. Sem a traducao dos DOIS lados, a recusa ficaria de pe sobre um
    campo que o lead acabou de responder."""
    assert campos_a_recusar(["faixa_preco_expressao"], ["faixa_preco_min_centavos"]) == set()


def test_nome_desconhecido_repetido_nao_infla_descartados(caplog):
    """Duplicata de nome DESCONHECIDO nao pode parecer supressao do filtro de PII.

    Um nome CONHECIDO repetido (`["regiao", "regiao"]`) tambem devolve so um
    elemento, mas isso e `conhecidos` sendo `set` -- nao prova nada sobre o
    `dict.fromkeys(recusou)` da funcao, porque o resultado seria identico sem
    ele. O dedupe so muda algo observavel no ramo dos nomes DESCONHECIDOS: sem
    ele, `["bairro_favorito", "bairro_favorito"]` teria `ignorados` com dois
    itens e `plausiveis` com um (o `sorted(set(...))` colapsa a duplicata), e
    `descartados = len(ignorados) - len(plausiveis)` sairia 1 -- como se o
    filtro tivesse suprimido um nome que na verdade so apareceu duas vezes.
    Mesmo raciocinio de `test_nome_repetido_nao_infla_descartados`, em
    `test_estado_marcado.py`, para `campos_a_marcar`.
    """
    with caplog.at_level(logging.WARNING):
        assert campos_a_recusar(["bairro_favorito", "bairro_favorito"], []) == set()

    assert '"nomes": ["bairro_favorito"]' in caplog.text
    assert '"descartados": 0' in caplog.text


def test_logga_o_nome_descartado_para_a_deriva_ser_vista(caplog):
    """Sem este log, o modelo mudar de vocabulario e invisivel -- mesma razao
    do log irmao em `campos_a_marcar` (`test_estado_marcado.py`)."""
    with caplog.at_level(logging.WARNING):
        campos_a_recusar(["bairro_favorito"], [])

    assert "estado.campo_recusado_desconhecido" in caplog.text
    assert "bairro_favorito" in caplog.text


def test_o_log_nao_carrega_o_que_nao_parece_nome_de_campo(caplog):
    """O modelo pode devolver texto em vez de nome, e texto pode ser o que o
    lead escreveu. Um nome que nao casa `[a-z_]{1,32}` e contado, nunca
    escrito -- mesma regra de PII de `campos_a_marcar`."""
    with caplog.at_level(logging.WARNING):
        campos_a_recusar(["Prefiro nao dizer onde moro"], [])

    assert "Prefiro nao dizer onde moro" not in caplog.text
    assert '"descartados"' in caplog.text
    assert '"nomes": []' in caplog.text


def test_sem_recusa_devolve_vazio():
    assert campos_a_recusar([], ["regiao"]) == set()
