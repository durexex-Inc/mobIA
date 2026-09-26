"""O job `eliminar_lead`: o fio entre a fila do ARQ e `eliminacao.anonimizar`. TEC-207, D4.

`DELETE /leads/{lead_id}/dados-pessoais` (`api/routes/titular.py`) enfileira
este job pelo nome (`ELIMINAR_LEAD_JOB`); aqui se prova que ele passa `ctx`
para `anonimizar` do jeito certo -- sessionmaker e armazem montado da
configuracao, nao um atalho que so funcionasse em teste.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.leads.repositorio import par_de, referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import registrar_solicitacao
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_sessionmaker
from mobia.workers.jobs.eliminar_lead import eliminar_lead

CANAL = "whatsapp"
TELEFONE = "5548999990099"
CHAVE = chave_de(CANAL, TELEFONE)
INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _ctx() -> dict[str, Any]:
    return {"session_factory": get_sessionmaker(), "settings": get_settings()}


async def _lead(session: AsyncSession, *, chave: str = CHAVE) -> uuid.UUID:
    await registrar(session, CANAL, TELEFONE)
    identificador = uuid.uuid4()
    session.add(
        Message(
            id=identificador,
            channel=CANAL,
            conversation_key=chave,
            role=MessageRole.LEAD,
            direction=MessageDirection.INBOUND,
            content_type=MessageContentType.TEXTO,
            sender_external_id=chave,
            text_body=encrypt("oi", aad_de(identificador, "text_body")),
            created_at=INICIO,
        )
    )
    apelidos = await referencias_para(session, [(CANAL, chave)])
    await session.commit()
    return apelidos[(CANAL, chave)]


async def test_o_job_anonimiza_e_fecha_a_solicitacao(
    session: AsyncSession, banco_limpo: None
) -> None:
    lead_id = await _lead(session)
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CHAVE,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    await eliminar_lead(_ctx(), str(solicitacao_id))

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ATENDIDA.value
    assert linha.channel is None
    assert linha.conversation_key is None
    # `referencias_de_lead` some junto -- o `leadId` do painel passa a dar 404.
    assert await par_de(session, lead_id) is None


async def test_o_job_ignora_solicitacao_de_acesso(session: AsyncSession, banco_limpo: None) -> None:
    """`anonimizar` so age sobre ELIMINACAO -- um id de ACESSO passado por
    engano nao apaga o lead que so pediu para ver os proprios dados."""
    lead_id = await _lead(session)
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CHAVE,
        tipo=TipoDeSolicitacao.ACESSO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    await eliminar_lead(_ctx(), str(solicitacao_id))

    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ABERTA.value
    assert await par_de(session, lead_id) is not None


async def test_o_job_ignora_solicitacao_ja_fechada(
    session: AsyncSession, banco_limpo: None
) -> None:
    """Retentativa do ARQ, ou clique duplo no painel: a segunda execucao ja
    nao tem par a anonimizar, e nao deve estourar."""
    await _lead(session)
    solicitacao_id = await registrar_solicitacao(
        session,
        channel=CANAL,
        conversation_key=CHAVE,
        tipo=TipoDeSolicitacao.ELIMINACAO,
        origem=OrigemDaSolicitacao.WHATSAPP,
        ator=ATOR_SISTEMA,
    )
    await session.commit()

    await eliminar_lead(_ctx(), str(solicitacao_id))
    # A segunda chamada nao deve levantar, mesmo com a solicitacao ja ATENDIDA.
    await eliminar_lead(_ctx(), str(solicitacao_id))


async def test_o_job_ignora_id_inexistente(banco_limpo: None) -> None:
    await eliminar_lead(_ctx(), str(uuid.uuid4()))
