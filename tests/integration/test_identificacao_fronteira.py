from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.agente.identificacao import e_conversa_nova
from mobia.infra.db import get_sessionmaker


async def test_lead_sem_historico_e_conversa_nova(session: AsyncSession, semear_entrada) -> None:
    """O caso que o predicado existe para pegar, e o que quase nao funciona.

    A ingestao grava a linha em `messages` ANTES de o worker existir, entao
    quando esta funcao roda a fala corrente JA esta no timeline. Uma consulta
    por "alguma mensagem nos ultimos 30 dias" acharia sempre a propria, e
    conversa nova seria permanentemente falso -- a identificacao nunca sairia,
    e todo teste de "nao repete na segunda mensagem" continuaria verde pelo
    motivo errado.
    """
    linha = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), linha) is True


async def test_mensagem_de_ontem_nao_e_conversa_nova(session: AsyncSession, semear_entrada) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_mensagem_de_31_dias_atras_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=31)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is True


async def test_mensagem_de_29_dias_atras_nao_e_conversa_nova(
    session: AsyncSession, semear_entrada
) -> None:
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=29)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_o_limite_exato_de_30_dias_tem_lado_definido(
    session: AsyncSession, semear_entrada
) -> None:
    """O empate nao fica ao acaso.

    A TEC-229 existe porque um teste de janela se apoiou em empate exato e deu
    falsa seguranca. Aqui o lado e escolhido e fixado: exatamente 30 dias de
    silencio ainda NAO abre conversa nova -- o corte e "mais de 30".
    """
    anterior = await semear_entrada(session)
    anterior.created_at = datetime.now(UTC) - timedelta(days=30)
    await session.commit()
    atual = await semear_entrada(session)

    assert await e_conversa_nova(get_sessionmaker(), atual) is False


async def test_mensagem_de_outro_lead_nao_conta(session: AsyncSession, semear_entrada) -> None:
    """O predicado e por lead, nao global. Sem o filtro de conversa, o primeiro
    lead do dia abriria conversa nova e nenhum outro abriria.
    """
    from mobia.domain.messages.models import Message

    outro = await semear_entrada(session)
    outro.conversation_key = "5511999998888"
    outro.created_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()

    atual = await semear_entrada(session)
    assert isinstance(atual, Message)
    assert await e_conversa_nova(get_sessionmaker(), atual) is True
