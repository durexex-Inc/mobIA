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

from mobia.domain.agente.classificador import SCHEMA_DA_EXTRACAO
from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.models import LeadQualification
from mobia.domain.context.montagem import _texto_do_estado
from mobia.domain.context.repositorio import campos_a_marcar, gravar_estado, marcar_perguntados


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


def test_marca_de_orcamento_entra_pelo_nome_que_o_modelo_conhece():
    """A cadeia da TEC-257 para orcamento estava partida em dois pontos, e a
    TEC-146 partiu os dois sem nenhum teste ficar vermelho.

    `SCHEMA_DA_EXTRACAO` tem UMA chave de preco, `faixa_preco_expressao`, e e
    a unica que o modelo pode escrever em `perguntou`. Ela nao e campo de
    `Extracao`, entao era descartada como vocabulario desconhecido -- com
    `estado.campo_perguntado_desconhecido` no log, a cada turno em que o
    agente perguntasse sobre orcamento. Efeito: o agente podia reperguntar
    orcamento para sempre.
    """
    assert campos_a_marcar(["faixa_preco_expressao"], set()) == {"faixa_preco_max"}


def test_marca_de_orcamento_sai_sob_a_chave_que_o_prompt_renderiza():
    """O segundo ponto partido: `perguntados_sem_resposta` guarda nomes, e
    `_texto_do_estado` compara os dele contra as CHAVES que renderiza
    (`faixa_preco_max`, em reais, pela ruling R6). `faixa_preco_max_centavos`
    em `perguntados_sem_resposta` nunca casaria nenhuma delas."""
    marcados = campos_a_marcar(["faixa_preco_expressao"], set())
    estado = LeadQualification(
        channel="whatsapp",
        conversation_key="c-1",
        intencao="COMPRA",
        perguntados_sem_resposta=sorted(marcados),
    )

    assert "faixa_preco_max: (perguntado, sem resposta)" in _texto_do_estado(estado)


def test_orcamento_respondido_por_qualquer_extremo_nao_e_marcado():
    """Marcar de MAIS e o erro caro: a marca e permanente, e mata o campo pela
    vida da conversa. "a partir de 300 mil" preenche so o minimo, e ainda
    assim o lead RESPONDEU a pergunta sobre orcamento."""
    assert campos_a_marcar(["faixa_preco_expressao"], {"faixa_preco_min_centavos"}) == set()
    assert campos_a_marcar(["faixa_preco_expressao"], {"faixa_preco_max_centavos"}) == set()


def test_toda_chave_do_estado_tem_marca_alcancavel():
    """Pina o MECANISMO que a ruling R6 criou, e nao a instancia dele.

    Sao tres vocabularios em serie -- o que o modelo pode dizer
    (`SCHEMA_DA_EXTRACAO`), o que a marca guarda
    (`perguntados_sem_resposta`), e o que o prompt renderiza
    (`_texto_do_estado`) -- e a TEC-146 fez os tres divergirem so para o
    orcamento. As duas direcoes abaixo sao o que a divergencia quebra:

    - **marca sem chave**: um nome que `campos_a_marcar` produz e que
      `_texto_do_estado` nao renderiza e uma marca que nunca aparece no
      prompt. E o que acontecia com `faixa_preco_max_centavos`.
    - **chave sem marca**: uma chave renderizavel que nenhum nome do
      vocabulario do modelo alcanca nunca recebe marca. E o que acontecia com
      `faixa_preco_max` pelo outro lado.

    As duas falham em SILENCIO -- o agente so repergunta mais -- e e por isso
    que elas precisam de um teste derivado das tres fontes em vez de uma
    lista escrita a mao.
    """
    cheio = LeadQualification(
        channel="whatsapp",
        conversation_key="c-1",
        intencao="COMPRA",
        faixa_preco_min_centavos=30_000_000,
        faixa_preco_max_centavos=45_000_000,
        regiao="pinheiros",
        tipo_imovel="APARTAMENTO",
        quartos=2,
        vagas=1,
        urgencia="IMEDIATA",
        forma_pagamento="FINANCIAMENTO",
        tem_imovel_para_vender=False,
    )
    chaves = {linha.split(":", 1)[0] for linha in _texto_do_estado(cheio).splitlines()}
    alcancaveis = {
        marca
        for nome in SCHEMA_DA_EXTRACAO["properties"]
        for marca in campos_a_marcar([nome], set())
    }

    # `intencao` nao e campo de extracao -- vem do classificador, e o modelo
    # nunca declara ter perguntado por ela. `faixa_preco_min` nao recebe marca
    # de proposito: orcamento e UM assunto, e a marca sai numa linha so, a
    # mesma que saia antes desta branch. Ver `_NOME_DA_MARCA`.
    sem_marca = {"intencao", "faixa_preco_min"}

    assert alcancaveis <= chaves, "marca que o prompt nunca renderiza"
    assert chaves - sem_marca <= alcancaveis, "chave que o modelo nunca consegue marcar"
    # Guarda contra a saida facil: se alguem esvaziar `_NOME_DA_MARCA`, as
    # duas assercoes acima ainda passariam com `faixa_preco_max` mudado para
    # `sem_marca`. Esta linha exige que a traducao exista de verdade.
    assert "faixa_preco_max" in alcancaveis


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


async def test_a_uniao_do_marcar_perguntados_e_sql_compilado_e_nao_leitura_previa() -> None:
    """A mesma trava do teste acima, para o UPDATE que producao de fato roda.

    Desde o commit que separou as duas fases, producao nao chama mais
    `gravar_estado` com `perguntou` -- quem grava a marca, depois da entrega
    confirmada, e `marcar_perguntados`, com um UPDATE avulso que o teste
    acima nao exercita nem podia (ele trava o ON CONFLICT DO UPDATE de
    `gravar_estado`, nao este). Sem este teste, a uniao deste UPDATE podia
    virar um SELECT + update em Python e nenhum teste desta suite reprovaria.
    """
    sessao = _SessaoQueCapturaOStatement()

    await marcar_perguntados(
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
    assert "|| %(coalesce_1)s" in sql_gerado
