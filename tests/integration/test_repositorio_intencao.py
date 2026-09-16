from decimal import Decimal

from sqlalchemy import text as sql

from mobia.domain.agente.repositorio import gravar_intencao, ler_intencao, marcar_desambiguacao
from mobia.domain.agente.schemas import Intencao

CANAL = "whatsapp"
CONVERSA = "5511911112222"


async def gravar(session, intencao: Intencao, confianca: str) -> int:
    fora_de_escopo_seguidas = await gravar_intencao(
        session,
        channel=CANAL,
        conversation_key=CONVERSA,
        intencao=intencao,
        confianca=Decimal(confianca),
        modelo="claude-opus-5",
    )
    await session.commit()
    return fora_de_escopo_seguidas


async def test_intencao_faz_roundtrip(session) -> None:
    await gravar(session, Intencao.COMPRA, "0.91")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.COMPRA
    assert lida.confianca == Decimal("0.91")
    assert lida.modelo == "claude-opus-5"


async def test_gravar_de_novo_atualiza_em_vez_de_duplicar(session) -> None:
    """Uma conversa tem uma intencao corrente, nao um historico delas."""
    await gravar(session, Intencao.INDEFINIDA, "0.40")
    await gravar(session, Intencao.INVESTIMENTO, "0.88")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.INVESTIMENTO

    total = await session.scalar(sql("SELECT count(*) FROM conversation_intent"))
    assert total == 1


async def test_regravar_a_mesma_intencao_move_o_updated_at(session) -> None:
    """A classificacao acontece a cada turno, mesmo quando nada muda.

    Uma linha que nao e reescrita nao distingue "continua COMPRA" de "nao foi
    classificado neste turno".
    """
    await gravar(session, Intencao.COMPRA, "0.91")
    primeiro = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    await gravar(session, Intencao.COMPRA, "0.93")
    segundo = await session.scalar(
        sql("SELECT updated_at FROM conversation_intent WHERE conversation_key = :k"),
        {"k": CONVERSA},
    )

    assert segundo > primeiro


async def test_conversa_sem_intencao_devolve_none(session) -> None:
    assert await ler_intencao(session, CANAL, "nunca-falou") is None


async def test_marcador_comeca_vazio(session) -> None:
    """Primeira ambiguidade de uma conversa nova tem de poder perguntar."""
    await gravar(session, Intencao.COMPRA, "0.45")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is None


async def test_marcar_desambiguacao_persiste(session) -> None:
    await gravar(session, Intencao.COMPRA, "0.45")

    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is not None


async def test_confianca_baixa_preserva_o_marcador(session) -> None:
    """O episodio de ambiguidade continua aberto -- a pergunta ja foi gasta."""
    await gravar(session, Intencao.COMPRA, "0.45")
    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    await gravar(session, Intencao.ALUGUEL, "0.50")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is not None, "ambiguidade que persiste nao devolve a pergunta"


async def test_confianca_no_limiar_limpa_o_marcador(session) -> None:
    """Uma classificacao confiante encerra o episodio e abre outro.

    E o limiar exato que faz isso, nao um valor folgado: a mesma borda dos dois
    lados da regra.
    """
    await gravar(session, Intencao.COMPRA, "0.45")
    await marcar_desambiguacao(session, channel=CANAL, conversation_key=CONVERSA)
    await session.commit()

    await gravar(session, Intencao.COMPRA, "0.60")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.desambiguado_em is None


async def test_efetiva_esconde_o_palpite_de_baixa_confianca(session) -> None:
    """A coluna guarda COMPRA; quem roteia enxerga INDEFINIDA."""
    await gravar(session, Intencao.COMPRA, "0.45")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.intencao is Intencao.COMPRA, "a tabela registra o classificador sem edicao"
    assert lida.efetiva is Intencao.INDEFINIDA


async def test_efetiva_devolve_a_intencao_quando_ha_confianca(session) -> None:
    await gravar(session, Intencao.ALUGUEL, "0.91")

    lida = await ler_intencao(session, CANAL, CONVERSA)
    assert lida is not None
    assert lida.efetiva is Intencao.ALUGUEL


async def test_fora_de_escopo_seguidas_sobe_a_cada_chamada(session) -> None:
    """RN-03.5, TEC-138. Duas mensagens fora de escopo seguidas contam 1 e 2."""
    primeira = await gravar(session, Intencao.FORA_DE_ESCOPO, "0.91")
    segunda = await gravar(session, Intencao.FORA_DE_ESCOPO, "0.91")

    assert primeira == 1
    assert segunda == 2


async def test_voltar_ao_assunto_zera_o_contador(session) -> None:
    """O "ELSE 0" do CASE em `gravar_intencao`: qualquer intencao que nao seja
    FORA_DE_ESCOPO zera, sem excecao -- e por isso o teste usa COMPRA, e nao
    precisa repetir para as outras seis.
    """
    await gravar(session, Intencao.FORA_DE_ESCOPO, "0.91")

    zerado = await gravar(session, Intencao.COMPRA, "0.91")

    assert zerado == 0


async def test_primeira_mensagem_fora_de_escopo_ja_conta_um(session) -> None:
    """O INSERT tambem tem de contar, e nao so o ON CONFLICT.

    Medido: sem `fora_de_escopo_seguidas` em `valores`, o INSERT gravava 0 na
    primeira mensagem de uma conversa nova, porque o CASE que soma so vive no
    `set_` do ON CONFLICT -- que nao roda quando a linha nasce agora.
    """
    primeira = await gravar(session, Intencao.FORA_DE_ESCOPO, "0.91")

    assert primeira == 1
