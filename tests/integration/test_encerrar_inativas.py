"""A varredura que fecha conversa parada. TEC-130, RN-02.3.

**O relogio conta da ultima fala do LEAD**, nao da ultima mensagem de
qualquer direcao: "sem interacao" e o lead sem interagir, e o agente falando
sozinho e a evidencia de que nao ha interacao.

**A propriedade e preventiva.** Nao existe hoje, em producao, uma linha
OUTBOUND que adie o encerramento: `sweep_followups` entrega por
`outbound.send` e nao grava em `messages`, e o unico criador de linha OUTBOUND
la e `MessageRecorder.record_agent_message`, que so roda dentro do turno,
segundos depois da INBOUND que o disparou. O que estes testes prendem e a
consulta, para que o dia em que alguem gravar uma fala nossa fora do turno nao
mude o encerramento de quem sumiu.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.conversa.models import Conversa
from mobia.domain.conversa.repositorio import (
    encerrar_conversa,
    encerrar_inativas,
    reabrir_conversa,
)
from mobia.domain.conversa.vocabulario import MotivoDoEncerramento, Status
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker

AGORA = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)


async def _semear(
    session: AsyncSession,
    *,
    chave: str,
    dias_atras: float,
    direction: MessageDirection = MessageDirection.INBOUND,
) -> None:
    """Uma linha em `messages`, so com o que a varredura le e o que a tabela exige.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL; `text_body` fica nulo de proposito -- nada nesta varredura
    decifra texto, e cifrar aqui so acrescentaria uma chave ao teste.
    """
    session.add(
        Message(
            id=uuid.uuid4(),
            channel="whatsapp",
            conversation_key=chave,
            role=(
                MessageRole.LEAD if direction is MessageDirection.INBOUND else MessageRole.AGENTE
            ),
            direction=direction,
            content_type=MessageContentType.TEXTO,
            created_at=AGORA - timedelta(days=dias_atras),
        )
    )
    await session.commit()


async def _status_de(session: AsyncSession, chave: str) -> tuple[str, str | None] | None:
    linha = (
        await session.execute(
            select(Conversa.status, Conversa.motivo_do_encerramento).where(
                Conversa.conversation_key == chave
            )
        )
    ).one_or_none()
    return None if linha is None else (linha.status, linha.motivo_do_encerramento)


@pytest.mark.usefixtures("banco_limpo")
async def test_trinta_dias_encerra(session: AsyncSession) -> None:
    await _semear(session, chave="lead-30", dias_atras=30)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 1
    assert await _status_de(session, "lead-30") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_vinte_e_nove_dias_nao_encerra(session: AsyncSession) -> None:
    """O empate resolve para o lado fechado, como `situacao_da_conversa` ja
    resolve o dela -- exatamente 30 encerra, 29 nao."""
    await _semear(session, chave="lead-29", dias_atras=29)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-29") is None


@pytest.mark.usefixtures("banco_limpo")
async def test_linha_outbound_recente_nao_adia_o_encerramento(session: AsyncSession) -> None:
    """Lead sumiu no dia 30; ha uma fala nossa no dia 14. Encerra assim mesmo.

    **O nome mudou porque o cenario nao ocorre em producao.** Ele era
    `test_o_followup_nao_adia_o_encerramento`, e narrava o follow-up da
    RN-13.1 gravando essa linha -- o que nao acontece: `sweep_followups`
    entrega por `outbound.send` e nao escreve em `messages`. A propriedade da
    consulta continua valendo e continua valendo a pena prender; o que saiu foi
    a atribuicao a um mecanismo que nao a produz. Ver a docstring do modulo.
    """
    await _semear(session, chave="lead-fup", dias_atras=30)
    await _semear(session, chave="lead-fup", dias_atras=14, direction=MessageDirection.OUTBOUND)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 1
    assert await _status_de(session, "lead-fup") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_nao_sobrescreve_motivo_de_encerramento_anterior(session: AsyncSession) -> None:
    """**Sem isto, toda conversa do sistema converge para INATIVIDADE.**

    `encerrar_conversa` e upsert idempotente de proposito, entao a varredura
    apagaria o motivo real 30 dias depois de ele ter sido escrito -- e o
    motivo e vocabulario justamente para nao perder essa distincao.
    """
    await _semear(session, chave="lead-fe", dias_atras=40)
    await encerrar_conversa(
        session,
        channel="whatsapp",
        conversation_key="lead-fe",
        motivo=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
        agora=AGORA - timedelta(days=35),
    )
    await session.commit()

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-fe") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.FORA_DE_ESCOPO,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_conversa_reaberta_volta_a_ser_candidata(session: AsyncSession) -> None:
    """**O ramo `ATIVA` do filtro, que nenhum outro teste executava.**

    Os demais cobrem os dois extremos -- conversa sem linha em `conversas`, e
    conversa com linha ENCERRADA -- e deixavam de fora justamente o
    `Conversa.status != Status.ENCERRADA`, que e a unica das tres condicoes
    que compara um `StrEnum` contra a coluna `String`.

    E o caso realista, nao um construto: a conversa fechou por fora de escopo,
    a janela venceu, o turno a reabriu, e agora o lead sumiu por 30 dias. Sem
    esta afirmacao, um filtro que so aceitasse linha ausente passaria em todos
    os outros testes e nunca fecharia uma conversa que ja teve encerramento.
    """
    await _semear(session, chave="lead-reaberta", dias_atras=40)
    await encerrar_conversa(
        session,
        channel="whatsapp",
        conversation_key="lead-reaberta",
        motivo=str(MotivoDoEncerramento.FORA_DE_ESCOPO),
        agora=AGORA - timedelta(days=90),
    )
    await reabrir_conversa(session, channel="whatsapp", conversation_key="lead-reaberta")
    await session.commit()
    assert await _status_de(session, "lead-reaberta") == (Status.ATIVA, None)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 1
    assert await _status_de(session, "lead-reaberta") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )


@pytest.mark.usefixtures("banco_limpo")
async def test_conversa_sem_nenhuma_fala_do_lead_nao_encerra(session: AsyncSession) -> None:
    """So OUTBOUND: nao ha fala do lead para medir o silencio a partir de.

    Encerrar aqui seria fechar a conversa de alguem que nunca falou, contando
    o relogio de uma mensagem nossa -- exatamente o que o `INBOUND` evita.
    """
    await _semear(session, chave="lead-mudo", dias_atras=45, direction=MessageDirection.OUTBOUND)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA)

    assert fechadas == 0
    assert await _status_de(session, "lead-mudo") is None


@pytest.mark.usefixtures("banco_limpo")
async def test_o_limite_corta_a_passagem(session: AsyncSession) -> None:
    for n in range(3):
        await _semear(session, chave=f"lead-{n}", dias_atras=40)

    fechadas = await encerrar_inativas(get_sessionmaker(), agora=AGORA, limite=2)

    assert fechadas == 2


@pytest.mark.usefixtures("banco_limpo")
async def test_o_job_fecha_e_devolve_a_contagem(session: AsyncSession) -> None:
    """O job e fino: pega a `session_factory` do `ctx` e devolve o numero.

    Mesmo molde de `sweep_sla` -- e o `startup` do worker que decide a
    implementacao, e o teste troca a decisao sem tocar no job.
    """
    from mobia.workers.jobs.sweep_conversas_inativas import sweep_conversas_inativas

    await _semear(session, chave="lead-job", dias_atras=40)

    fechadas = await sweep_conversas_inativas({"session_factory": get_sessionmaker()})

    assert fechadas == 1
    assert await _status_de(session, "lead-job") == (
        Status.ENCERRADA,
        MotivoDoEncerramento.INATIVIDADE,
    )
