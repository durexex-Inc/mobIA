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

from sqlalchemy.dialects import postgresql

from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.repositorio import campos_a_marcar, gravar_estado


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
    assert '"descartados": 0' in caplog.text, (
        "nada foi suprimido pelo filtro de PII aqui -- 'bairro' passou no "
        "fullmatch e foi logado. Um descartados > 0 mentiria sobre supressao"
    )


def test_nome_repetido_nao_infla_descartados(caplog):
    """Duplicata nao pode parecer supressao do filtro de PII.

    Sem dedupe, `["bairro", "bairro"]` teria `ignorados=["bairro", "bairro"]`
    e `plausiveis=["bairro"]` (o `sorted(set(...))` colapsa a duplicata), e
    `descartados = len(ignorados) - len(plausiveis)` sairia 1 -- como se o
    filtro tivesse suprimido um nome que na verdade so apareceu duas vezes.
    E o unico instrumento que esta card tem para a deriva de vocabulario do
    modelo, e ele nao pode mentir sobre a propria supressao.
    """
    with caplog.at_level(logging.WARNING):
        campos_a_marcar(["bairro", "bairro"], set())

    assert '"nomes": ["bairro"]' in caplog.text
    assert '"descartados": 0' in caplog.text


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


class _SessaoQueCapturaOStatement:
    """Duble minimo: guarda o statement que `gravar_estado` mandaria executar.

    Nao herda de `AsyncSession` -- so precisa do unico metodo que
    `gravar_estado` chama, e nao abre conexao nenhuma.
    """

    def __init__(self) -> None:
        self.statement: object = None

    async def execute(self, statement: object) -> None:
        self.statement = statement


async def test_a_uniao_e_sql_compilado_e_nao_leitura_previa() -> None:
    """Trava o mecanismo que `test_a_marca_e_uniao_e_nao_substituicao` nao trava.

    Aquele teste (integracao) roda duas chamadas sequenciais e passaria
    identico com uma implementacao Python de ler-unir-em-memoria-e-gravar --
    o comportamento que a uniao em SQL existe para garantir (as duas marcas
    sobrevivem a dois turnos concorrentes, sem janela de leitura) fica sem
    nenhum teste que reprove se alguem "simplificar" `gravar_estado` para um
    SELECT + update em Python. Sem banco: compila o statement contra o
    dialeto do postgres e olha o SQL gerado, exatamente o `ON CONFLICT DO
    UPDATE` que `gravar_estado` monta hoje.
    """
    sessao = _SessaoQueCapturaOStatement()

    await gravar_estado(
        sessao,
        channel="wa",
        conversation_key="k",
        intencao=Intencao.COMPRA,
        extracao=Extracao(quartos=2),
        perguntou=["regiao"],
    )

    assert sessao.statement is not None
    sql_gerado = str(sessao.statement.compile(dialect=postgresql.dialect()))

    assert "coalesce(lead_qualification.perguntados_sem_resposta" in sql_gerado
    assert "|| excluded.perguntados_sem_resposta" in sql_gerado
