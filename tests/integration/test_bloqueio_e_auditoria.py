import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.messages.bloqueio import marcar_bloqueada, registrar_bloqueio_de_saida
from mobia.domain.messages.models import Message
from mobia.domain.moderacao.models import ModerationEvent
from mobia.infra.db import get_sessionmaker


async def test_a_marca_e_o_evento_saem_na_mesma_transacao(
    session: AsyncSession, semear_entrada
) -> None:
    """Um commit so. Sem isso existiria o estado "mensagem marcada como
    bloqueada, recusa nao auditada", que e o estado em que o controle da
    RN-B04 falha em silencio -- a marca protege o contexto do agente e nao
    prova nada sobre a auditoria.
    """
    linha = await semear_entrada(session)

    await marcar_bloqueada(
        get_sessionmaker(),
        linha.id,
        channel=linha.channel,
        conversation_key=linha.conversation_key,
        categoria="DISCRIMINACAO",
    )

    marcada = await session.scalar(select(Message).where(Message.id == linha.id))
    # `marcar_bloqueada` escreveu em outra sessao (a de `session_factory`), e o
    # identity map desta sessao devolveria o objeto que `semear_entrada` ja
    # tinha carregado, sem reler a coluna do banco -- sem o refresh a marca
    # ficaria invisivel aqui mesmo tendo sido gravada.
    await session.refresh(marcada)
    evento = await session.scalar(select(ModerationEvent))
    assert marcada is not None and marcada.bloqueada_em is not None
    assert evento is not None
    assert evento.direcao == "ENTRADA"
    assert evento.categoria == "DISCRIMINACAO"
    assert evento.message_id == linha.id
    assert evento.channel == linha.channel
    assert evento.conversation_key == linha.conversation_key


async def test_falha_na_gravacao_nao_deixa_marca_sem_evento(
    session: AsyncSession, semear_entrada, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transacao unica so vale se ela reverter junto. Com dois commits, a
    marca sobreviveria a falha do evento e produziria o estado duravel
    "marcada, nao auditada" -- o estado em que o controle de risco da RN-B04
    falha em silencio.
    """
    linha = await semear_entrada(session)

    import mobia.domain.messages.bloqueio as modulo

    def explodir(*args: object, **kwargs: object) -> None:
        raise RuntimeError("banco fora")

    monkeypatch.setattr(modulo, "ModerationEvent", explodir)

    with pytest.raises(RuntimeError):
        await marcar_bloqueada(
            get_sessionmaker(),
            linha.id,
            channel=linha.channel,
            conversation_key=linha.conversation_key,
            categoria="DISCRIMINACAO",
        )

    await session.rollback()
    marcada = await session.scalar(select(Message).where(Message.id == linha.id))
    # Mesmo motivo do teste acima: sem o refresh este teste passaria mesmo que
    # o UPDATE tivesse sido commitado (verde pelo motivo errado), porque o
    # objeto em memoria nunca tinha `bloqueada_em` preenchido para comecar.
    await session.refresh(marcada)
    assert marcada is not None and marcada.bloqueada_em is None
    assert await session.scalar(select(ModerationEvent)) is None


async def test_o_bloqueio_de_saida_grava_evento_sem_marca(
    session: AsyncSession, semear_entrada
) -> None:
    """A saida nao tem linha propria em `messages` para carimbar: o texto
    barrado nunca foi persistido, e nao sera. O `message_id` aponta para a
    mensagem de ENTRADA que originou o turno, que e a ancora que existe.
    """
    linha = await semear_entrada(session)

    await registrar_bloqueio_de_saida(
        get_sessionmaker(),
        message_id=linha.id,
        channel=linha.channel,
        conversation_key=linha.conversation_key,
        categoria="NEGOCIACAO",
    )

    evento = await session.scalar(select(ModerationEvent))
    marcada = await session.scalar(select(Message).where(Message.id == linha.id))
    # Aqui nao ha escrita em `messages` para este bloqueio -- so por simetria
    # com os dois testes acima, e para deixar explicito que a linha realmente
    # nao mudou (o refresh nao teria nada novo a trazer, mas mantem o padrao
    # de nunca confiar no identity map para provar ausencia de escrita alheia).
    await session.refresh(marcada)
    assert evento is not None and evento.direcao == "SAIDA"
    assert evento.categoria == "NEGOCIACAO"
    assert marcada is not None and marcada.bloqueada_em is None
