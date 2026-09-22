"""A trilha de tarefas para o corretor. TEC-186, RN-13.6.

Integracao: o registro append-only e a idempotencia por tentativa so da para
verificar contra o banco.
"""

import uuid
from datetime import UTC, datetime

from mobia.domain.context.temperatura import Temperatura
from mobia.domain.followup.repositorio import (
    MOTIVO_SEM_TEMPLATE,
    Candidato,
    listar_tarefas_de_corretor,
    registrar_tarefa_de_corretor,
)
from mobia.domain.followup.template import CATEGORIA_CONVITE

CANAL = "whatsapp"
CONVERSA = "5511944443333"
ANCORA = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def _candidato() -> Candidato:
    return Candidato(
        channel=CANAL,
        conversation_key=CONVERSA,
        temperatura=Temperatura.MORNO,
        ancora_em=ANCORA,
        ancora_message_id=uuid.uuid4(),
        ja_disparada=1,
        ja_enviadas=1,
    )


async def test_grava_e_le_a_tarefa(session) -> None:
    """Cenario 3: uma tarefa e criada para o corretor."""
    tarefa = await registrar_tarefa_de_corretor(
        session,
        candidato=_candidato(),
        tentativa=2,
        categoria=CATEGORIA_CONVITE,
        motivo=MOTIVO_SEM_TEMPLATE,
    )
    await session.commit()

    assert tarefa is not None
    lidas = await listar_tarefas_de_corretor(session, channel=CANAL, conversation_key=CONVERSA)
    assert len(lidas) == 1
    assert lidas[0].categoria == CATEGORIA_CONVITE
    assert lidas[0].motivo == MOTIVO_SEM_TEMPLATE
    assert lidas[0].tentativa_numero == 2


async def test_a_mesma_tentativa_nao_duplica(session) -> None:
    """A UNIQUE espelha `followups`: idempotencia por tentativa."""
    primeira = await registrar_tarefa_de_corretor(
        session,
        candidato=_candidato(),
        tentativa=2,
        categoria=CATEGORIA_CONVITE,
        motivo=MOTIVO_SEM_TEMPLATE,
    )
    await session.commit()
    segunda = await registrar_tarefa_de_corretor(
        session,
        candidato=_candidato(),
        tentativa=2,
        categoria=CATEGORIA_CONVITE,
        motivo=MOTIVO_SEM_TEMPLATE,
    )
    await session.commit()

    assert primeira is not None
    assert segunda is None
    lidas = await listar_tarefas_de_corretor(session, channel=CANAL, conversation_key=CONVERSA)
    assert len(lidas) == 1
