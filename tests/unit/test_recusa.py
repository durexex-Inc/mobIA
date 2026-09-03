"""A regra da recusa de campo, sem banco.

TEC-148.
"""

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


def test_nomes_repetidos_nao_duplicam():
    assert campos_a_recusar(["regiao", "regiao"], []) == {"regiao"}


def test_sem_recusa_devolve_vazio():
    assert campos_a_recusar([], ["regiao"]) == set()
