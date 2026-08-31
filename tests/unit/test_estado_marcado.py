"""A regra de marcacao da TEC-257, sem banco.

Puro de proposito: e a mesma funcao que producao e o runner do eval chamam,
e o que ela decide nao depende de sessao nenhuma.

`caplog.at_level` e as assercoes por chave (`'"descartados"'`, e nao
`descartados=1`) sao obrigatorias: `configure_logging` usa
`structlog.stdlib.LoggerFactory` com JSONRenderer, entao o que chega em
`caplog.text` e JSON. Assercao sobre o formato do valor quebra a cada mudanca
de renderer -- e a forma que `test_classificar_loga_metricas_sem_conteudo` ja
usa.
"""

import logging

from mobia.domain.context.repositorio import campos_a_marcar


def test_marca_o_que_foi_perguntado_e_nao_esta_preenchido():
    assert campos_a_marcar(["regiao", "vagas"], set()) == {"regiao", "vagas"}


def test_nao_marca_o_que_ja_esta_preenchido():
    """Campo no estado e reperguntado e territorio do proxy irmao.

    `_reperguntou` (no runner do eval) mede perguntar o que o estado JA SABE.
    Aqui interessa so o que o lead nao respondeu.
    """
    assert campos_a_marcar(["regiao", "vagas"], {"regiao"}) == {"vagas"}


def test_descarta_nome_que_nao_e_campo_de_extracao():
    """Nome inventado marca de MENOS, e esse e o erro seguro.

    Com a marca permanente (D1 do spec), marcar de mais mata o campo pela
    vida da conversa e em silencio. Nao marcar so custa uma pergunta a mais.
    """
    assert campos_a_marcar(["regiao", "bairro", "intencao"], set()) == {"regiao"}


def test_logga_o_nome_descartado_para_a_deriva_ser_vista(caplog):
    """Sem este log, o modelo mudar de vocabulario e invisivel.

    E o buraco que a card acusa na opcao do proxy -- "o erro fica invisivel".
    """
    with caplog.at_level(logging.WARNING):
        campos_a_marcar(["bairro"], set())

    assert "estado.campo_perguntado_desconhecido" in caplog.text
    assert "bairro" in caplog.text


def test_o_log_nao_carrega_o_que_nao_parece_nome_de_campo(caplog):
    """O modelo pode devolver texto em vez de nome, e texto pode ser do lead.

    Um nome que nao casa `[a-z_]{1,32}` e contado, nunca escrito. A regra de
    PII vale para tudo o que vem de uma chamada ao modelo.
    """
    with caplog.at_level(logging.WARNING):
        campos_a_marcar(["Regiao: Vila Mariana, perto da USP"], set())

    assert "Vila Mariana" not in caplog.text
    assert '"descartados"' in caplog.text
    assert '"nomes": []' in caplog.text


def test_vazio_nao_logga_nada(caplog):
    with caplog.at_level(logging.WARNING):
        assert campos_a_marcar([], {"regiao"}) == set()

    assert caplog.text == ""
