"""A dobra forcada: a conversa nova ve o resumo, nunca a transcricao. TEC-130, D4.

**A fronteira e a marca do resumo**, e nao uma coluna nova nem um filtro por
`encerrada_em`: dobrando tudo o que ficou para tras, a marca passa a cobrir a
conversa anterior inteira e `literais_apos` devolve so o que e novo.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.domain.context.montagem import montar_contexto
from mobia.domain.context.resumo import ResumoGerado
from mobia.domain.messages.enums import (
    MessageContentType,
    MessageDirection,
    MessageRole,
)
from mobia.domain.messages.models import Message
from mobia.infra.db import get_sessionmaker


class _ResumidorFalso:
    """Devolve um texto fixo e registra o que lhe pediram para dobrar."""

    def __init__(self) -> None:
        self.conteudos: list[str] = []

    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        self.conteudos.append(conteudo)
        return ResumoGerado(
            texto="Lead procurava apartamento de dois quartos na zona sul.",
            modelo="falso",
            tokens_in=10,
            tokens_out=10,
            latency_ms=1,
        )


class _ResumidorQuebrado:
    async def resumir(self, instrucao: str, conteudo: str) -> ResumoGerado:
        raise RuntimeError("provedor fora do ar")


class _ContadorFalso:
    async def contar(self, texto: str) -> int:
        return 10


async def _semear_conversa(session: AsyncSession, chave: str, quantas: int) -> None:
    """Uma conversa velha, alternando lead e agente.

    `channel`, `conversation_key`, `role`, `direction` e `content_type` sao
    NOT NULL. `text_body` fica nulo: `_texto_das` (em `montagem.py`) lida com
    isso, e o que este teste afirma e sobre QUANTAS mensagens sobram, nao
    sobre o que elas diziam.
    """
    base = datetime.now(UTC) - timedelta(days=60)
    for n in range(quantas):
        do_lead = n % 2 == 0
        session.add(
            Message(
                id=uuid.uuid4(),
                channel="whatsapp",
                conversation_key=chave,
                role=MessageRole.LEAD if do_lead else MessageRole.AGENTE,
                direction=(MessageDirection.INBOUND if do_lead else MessageDirection.OUTBOUND),
                content_type=MessageContentType.TEXTO,
                created_at=base + timedelta(minutes=n),
            )
        )
    await session.commit()


@pytest.mark.usefixtures("banco_limpo")
async def test_a_dobra_forcada_nao_deixa_literal_nenhum(session: AsyncSession) -> None:
    """**O criterio da card ao pe da letra**: por meio do resumo, nao pela
    transcricao inteira.

    Cinco mensagens ficam MUITO abaixo do gatilho de regeneracao (40) e do
    piso de literais (20) -- sem a dobra forcada, as cinco iriam inteiras
    para o prompt da conversa nova.
    """
    await _semear_conversa(session, "lead-reabre", quantas=5)
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-reabre",
        resumidor=resumidor,
        contador=_ContadorFalso(),
        forcar_dobra=True,
    )

    assert montado.literais == []
    assert montado.resumo is not None
    assert len(resumidor.conteudos) == 1


@pytest.mark.usefixtures("banco_limpo")
async def test_sem_a_flag_o_piso_preserva_os_literais(session: AsyncSession) -> None:
    """A contraprova: o comportamento de sempre nao mudou."""
    await _semear_conversa(session, "lead-normal", quantas=5)
    resumidor = _ResumidorFalso()

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-normal",
        resumidor=resumidor,
        contador=_ContadorFalso(),
    )

    assert len(montado.literais) == 5
    assert resumidor.conteudos == []


@pytest.mark.usefixtures("banco_limpo")
async def test_resumo_falho_degrada_e_nao_mata_o_turno(session: AsyncSession) -> None:
    """**A degradacao declarada da D4.**

    Perder resumo E literais deixaria o agente cego diante de um lead que ele
    ja atendeu. Ver demais e menos ruim que nao ver nada -- entao os literais
    voltam, e o warning denuncia.
    """
    await _semear_conversa(session, "lead-quebrado", quantas=5)

    montado = await montar_contexto(
        get_sessionmaker(),
        channel="whatsapp",
        conversation_key="lead-quebrado",
        resumidor=_ResumidorQuebrado(),
        contador=_ContadorFalso(),
        forcar_dobra=True,
    )

    assert len(montado.literais) == 5
