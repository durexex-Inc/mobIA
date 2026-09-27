"""O job `eliminar_lead`: o fio entre a fila do ARQ e `eliminacao.anonimizar`. TEC-207, D4.

`DELETE /leads/{lead_id}/dados-pessoais` (`api/routes/titular.py`) enfileira
este job pelo nome (`ELIMINAR_LEAD_JOB`); aqui se prova que ele passa `ctx`
para `anonimizar` do jeito certo -- o sessionmaker e o armazem que o
`startup` do worker grava em `ctx` (`ctx["armazem"]`, o mesmo que o sweep de
retencao usa), nao um atalho que so funcionasse em teste.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from arq import Retry
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mobia.app.config import get_settings
from mobia.domain.auditoria.vocabulario import ATOR_SISTEMA
from mobia.domain.identidade.indice import chave_de, registrar
from mobia.domain.leads.repositorio import par_de, referencias_para
from mobia.domain.messages.enums import MessageContentType, MessageDirection, MessageRole
from mobia.domain.messages.models import Message
from mobia.domain.midia.armazem import armazem_da_config
from mobia.domain.titular import eliminacao
from mobia.domain.titular.models import SolicitacaoDeTitular
from mobia.domain.titular.repositorio import registrar_solicitacao
from mobia.domain.titular.vocabulario import (
    OrigemDaSolicitacao,
    StatusDaSolicitacao,
    TipoDeSolicitacao,
)
from mobia.infra.crypto import aad_de, encrypt
from mobia.infra.db import get_engine, get_sessionmaker
from mobia.workers.jobs.eliminar_lead import eliminar_lead

CANAL = "whatsapp"
TELEFONE = "5548999990099"
CHAVE = chave_de(CANAL, TELEFONE)
INICIO = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _ctx() -> dict[str, Any]:
    """As chaves que `workers/main.py::startup` grava -- sem `settings`, de
    proposito: o job le o armazem pronto, como o sweep de retencao, e nao
    monta um segundo a partir da configuracao (revisao final, M3)."""
    return {"session_factory": get_sessionmaker(), "armazem": armazem_da_config(get_settings())}


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


async def test_escritor_aberto_faz_a_anonimizacao_desistir_e_nao_fechar_nada(
    session: AsyncSession, banco_limpo: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revisao final, M1. `anonimizar_lead` desliga as triggers com ALTER
    TABLE, que pede SHARE ROW EXCLUSIVE em `lead_score_audit` e
    `conversation_intent_audit`. Sem `lock_timeout`, uma transacao aberta que
    ja escreveu numa delas deixava a anonimizacao esperando -- e todo turno
    que grava score enfileirava atras dela. Com o teto, ela desiste, a
    transacao volta inteira e a solicitacao continua ABERTA para a proxima
    tentativa.

    O bloqueador e um ESCRITOR (ROW EXCLUSIVE, o lock de um INSERT), e nao um
    leitor: o ACCESS SHARE de um SELECT nao conflita com SHARE ROW EXCLUSIVE,
    e a primeira versao deste teste, com um SELECT aberto, viu a anonimizacao
    passar."""
    monkeypatch.setattr(eliminacao, "LOCK_TIMEOUT_DA_ANONIMIZACAO", "200ms")
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

    async with get_engine().connect() as escritor:
        # Transacao aberta com o lock que um INSERT de score segura.
        await escritor.execute(text("LOCK TABLE lead_score_audit IN ROW EXCLUSIVE MODE"))
        with pytest.raises(eliminacao.AnonimizacaoSemLock):
            await asyncio.wait_for(
                eliminacao.anonimizar(
                    get_sessionmaker(), _ctx()["armazem"], solicitacao_id=solicitacao_id
                ),
                timeout=30,
            )
        await escritor.rollback()

    session.expire_all()
    linha = (
        await session.execute(
            select(SolicitacaoDeTitular).where(SolicitacaoDeTitular.id == solicitacao_id)
        )
    ).scalar_one()
    assert linha.status == StatusDaSolicitacao.ABERTA.value
    assert await par_de(session, lead_id) is not None


async def test_o_job_sem_lock_pede_retentativa_ao_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """O job transforma a desistencia por lock em `Retry`: a proxima tentativa
    do ARQ tende a achar o bloqueador ja terminado, e esgotadas as tentativas a retencao
    ainda cumpre a solicitacao antes do prazo."""

    async def sem_lock(*_: Any, **__: Any) -> None:
        raise eliminacao.AnonimizacaoSemLock("lock_timeout")

    monkeypatch.setattr("mobia.workers.jobs.eliminar_lead.anonimizar", sem_lock)

    with pytest.raises(Retry):
        await eliminar_lead(_ctx(), str(uuid.uuid4()))
