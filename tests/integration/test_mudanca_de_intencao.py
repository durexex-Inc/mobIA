"""O descarte do orcamento quando a intencao troca de banda. TEC-136."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mobia.domain.agente.schemas import Extracao, Intencao
from mobia.domain.context.models import ConversationIntentAudit, LeadQualification
from mobia.domain.context.montagem import _MARCA_SEM_RESPOSTA, _texto_do_estado
from mobia.domain.context.repositorio import (
    aplicar_mudanca_de_intencao,
    gravar_estado,
    ler_estado,
)

CANAL = "whatsapp"


async def _semear(session, chave: str, intencao: Intencao, **extras) -> None:
    """Grava um estado inicial pelo caminho de producao, e nao por INSERT cru.

    Passar pelo `gravar_estado` de verdade e o que garante que o estado de
    partida destes testes e um estado que o turno de fato produz -- um INSERT
    a mao poderia montar combinacao que `campos_a_gravar` nunca gera.
    """
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key=chave,
        intencao=intencao,
        extracao=Extracao(**extras),
    )
    await session.flush()


async def test_trocar_de_aluguel_para_compra_descarta_o_orcamento(session) -> None:
    """O cenario 2 do Gherkin: o valor mensal nao vira faixa de preco de compra.

    R$ 2.500 e um aluguel plausivel e um preco de compra absurdo. Ate esta
    card ele sobrevivia a troca e virava o filtro da busca de compra.
    """
    # 250_000 centavos = R$ 2.500. Dentro de `_BANDA_DE_ALUGUEL` (R$ 300 a
    # R$ 200 mil) e ABAIXO do piso de `_BANDA_DE_COMPRA` (R$ 30 mil): e o par
    # de numeros que torna o cenario da card verificavel em vez de plausivel.
    await _semear(
        session,
        "5511900000001",
        Intencao.ALUGUEL,
        faixa_preco_max_centavos=250_000,
        regiao="zona sul",
        quartos=2,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000001",
        intencao=Intencao.COMPRA,
    )

    assert mudanca is not None
    assert mudanca.faixa_descartada is True

    estado = await ler_estado(session, CANAL, "5511900000001")
    assert estado is not None
    assert estado.faixa_preco_min_centavos is None
    assert estado.faixa_preco_max_centavos is None
    # O cenario 1 do Gherkin, na mesma asserta: o que continua valido fica.
    assert estado.regiao == "zona sul"
    assert estado.quartos == 2


async def test_o_orcamento_volta_a_ser_perguntavel(session) -> None:
    """A D4: descartar o campo sem tirar a marca nao repergunta nada.

    Afirma o EFEITO no texto que o modelo le, e nao o conteudo do array. O
    array e meio: quem decide se o agente repergunta e `_texto_do_estado`, que
    emite `faixa_preco_max: (perguntado, sem resposta)` enquanto a marca
    estiver la. Com essa linha no prompt o orcamento e assunto encerrado, e o
    cenario 2 do Gherkin ("E o agente pergunta o orcamento de compra") nunca
    acontece. Sumir do texto -- sem valor e sem marca -- e o unico estado em
    que o agente volta a perguntar.
    """
    await gravar_estado(
        session,
        channel=CANAL,
        conversation_key="5511900000002",
        intencao=Intencao.ALUGUEL,
        extracao=Extracao(regiao="centro"),
        perguntou=("faixa_preco_expressao",),
    )
    await session.flush()
    antes = await ler_estado(session, CANAL, "5511900000002")
    assert antes is not None
    assert f"faixa_preco_max: {_MARCA_SEM_RESPOSTA}" in _texto_do_estado(antes)

    await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000002",
        intencao=Intencao.COMPRA,
    )

    depois = await ler_estado(session, CANAL, "5511900000002")
    assert depois is not None
    assert "faixa_preco_max" not in _texto_do_estado(depois)


async def test_mesma_banda_preserva_o_orcamento(session) -> None:
    """A contraprova. Sem ela, um descarte incondicional passaria nos outros."""
    await _semear(
        session,
        "5511900000003",
        Intencao.COMPRA,
        faixa_preco_max_centavos=80_000_000,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000003",
        intencao=Intencao.INVESTIMENTO,
    )

    assert mudanca is not None
    assert mudanca.faixa_descartada is False
    estado = await ler_estado(session, CANAL, "5511900000003")
    assert estado is not None
    assert estado.faixa_preco_max_centavos is not None


async def test_turno_indefinido_nao_muda_nada(session) -> None:
    """INDEFINIDA nunca grava intencao, entao nunca pode disparar descarte.

    E o turno mais comum de todos depois do primeiro: um "obrigado" no meio da
    conversa classifica INDEFINIDA. Se ele descartasse, o orcamento do lead
    evaporaria por educacao.
    """
    await _semear(
        session,
        "5511900000004",
        Intencao.ALUGUEL,
        faixa_preco_max_centavos=250_000,
    )

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000004",
        intencao=Intencao.INDEFINIDA,
    )

    assert mudanca is None
    estado = await ler_estado(session, CANAL, "5511900000004")
    assert estado is not None
    assert estado.faixa_preco_max_centavos is not None


async def test_a_mudanca_grava_uma_linha_de_historico(session) -> None:
    """Uma linha por troca, com origem e destino."""
    await _semear(session, "5511900000005", Intencao.ALUGUEL, regiao="centro")

    await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000005",
        intencao=Intencao.COMPRA,
    )
    await session.flush()

    linhas = (
        await session.scalars(
            select(ConversationIntentAudit).where(
                ConversationIntentAudit.conversation_key == "5511900000005"
            )
        )
    ).all()
    assert len(linhas) == 1
    assert linhas[0].de == Intencao.ALUGUEL.value
    assert linhas[0].para == Intencao.COMPRA.value


async def test_a_intencao_repetida_nao_grava_historico(session) -> None:
    """Todo turno chama esta funcao; so a MUDANCA gera linha.

    Sem esta guarda a tabela ganharia uma linha por turno, que e exatamente o
    que o docstring do modelo diz que ela nao e.
    """
    await _semear(session, "5511900000006", Intencao.COMPRA, regiao="centro")

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000006",
        intencao=Intencao.COMPRA,
    )
    await session.flush()

    assert mudanca is None
    linhas = (
        await session.scalars(
            select(ConversationIntentAudit).where(
                ConversationIntentAudit.conversation_key == "5511900000006"
            )
        )
    ).all()
    assert linhas == []


async def test_sem_linha_de_qualificacao_nao_faz_nada(session) -> None:
    """Primeiro turno da conversa: nao ha estado, nao ha o que descartar.

    `aplicar_mudanca_de_intencao` roda ANTES de `gravar_estado`, entao no
    primeiro turno a linha ainda nem existe. Devolver None aqui e o que impede
    a funcao de criar linha -- criar moveria o score do lead pelo mesmo
    argumento que o `if not campos:` de `gravar_estado` ja registra.
    """
    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000007",
        intencao=Intencao.COMPRA,
    )

    assert mudanca is None
    assert await session.get(LeadQualification, (CANAL, "5511900000007")) is None


async def test_o_cadeado_serializa_dois_turnos_da_mesma_conversa(
    session, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """O `FOR UPDATE` e o unico ponto que serializa dois turnos concorrentes.

    A deduplicacao do ARQ e por mensagem, nao por conversa: duas falas do mesmo
    lead chegando juntas produzem dois jobs em paralelo. Sem o cadeado os dois
    leem a mesma intencao anterior e ambos gravam linha de historico para a
    mesma troca. Segue o molde do teste irmao de `registrar_recalculo`: com o
    cadeado a segunda chamada bloqueia no primeiro statement e o `wait_for`
    estoura; sem ele a chamada atravessa na hora e nao ha `TimeoutError`.

    A troca e COMPRA -> INVESTIMENTO, da mesma banda, de proposito: ela nao
    descarta nada, entao a funcao nao emite UPDATE nenhum em
    `lead_qualification`. E o que faz este teste falar do cadeado na LEITURA.
    Com uma troca que descarta, o UPDATE tambem bloquearia e o `TimeoutError`
    apareceria mesmo com o `FOR UPDATE` removido -- o teste passaria afirmando
    que o cadeado existe quando ele so estaria sendo tomado tarde demais, ja
    depois da leitura que decide.
    """
    await _semear(session, "5511900000008", Intencao.COMPRA, faixa_preco_max_centavos=80_000_000)
    await session.commit()

    async with session_factory() as segurando, session_factory() as bloqueada:
        await segurando.execute(
            select(LeadQualification)
            .where(
                LeadQualification.channel == CANAL,
                LeadQualification.conversation_key == "5511900000008",
            )
            .with_for_update()
        )
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(
                    aplicar_mudanca_de_intencao(
                        bloqueada,
                        channel=CANAL,
                        conversation_key="5511900000008",
                        intencao=Intencao.INVESTIMENTO,
                    ),
                    timeout=1,
                )
        finally:
            # Solta o cadeado antes de qualquer outra coisa: sem isto o proximo
            # teste do arquivo esperaria por ele ate o timeout do pytest.
            await segurando.rollback()
            await bloqueada.rollback()


async def test_a_decisao_sai_da_linha_sob_o_cadeado_e_nao_do_cache_da_sessao(
    session, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Tomar o cadeado nao basta: a decisao tem de usar o que ele releu.

    O turno le o estado nesta mesma sessao para montar o prompt, entao a linha
    ja esta no identity map quando esta funcao roda. Sem `populate_existing`, o
    ORM devolve a instancia velha e joga fora as colunas que o `FOR UPDATE`
    acabou de reler -- o cadeado ficaria tomado e inutil.

    Aqui o outro turno ja COMMITOU a troca para COMPRA. Lendo sob o cadeado,
    `antiga` e COMPRA, nao ha mudanca e nada se grava. Lendo do cache, `antiga`
    seria ALUGUEL e este turno gravaria uma SEGUNDA linha de historico para a
    troca que o outro ja registrou -- e descartaria o orcamento de novo.
    """
    await _semear(session, "5511900000009", Intencao.ALUGUEL, faixa_preco_max_centavos=250_000)
    await session.commit()

    cacheado = await ler_estado(session, CANAL, "5511900000009")
    assert cacheado is not None
    assert cacheado.intencao == Intencao.ALUGUEL.value
    await session.commit()

    async with session_factory() as outro_turno:
        await outro_turno.execute(
            text(
                "UPDATE lead_qualification SET intencao = :i "
                "WHERE channel = :c AND conversation_key = :k"
            ),
            {"i": Intencao.COMPRA.value, "c": CANAL, "k": "5511900000009"},
        )
        await outro_turno.commit()

    mudanca = await aplicar_mudanca_de_intencao(
        session,
        channel=CANAL,
        conversation_key="5511900000009",
        intencao=Intencao.COMPRA,
    )
    await session.flush()

    assert mudanca is None
    linhas = (
        await session.scalars(
            select(ConversationIntentAudit).where(
                ConversationIntentAudit.conversation_key == "5511900000009"
            )
        )
    ).all()
    assert linhas == []
