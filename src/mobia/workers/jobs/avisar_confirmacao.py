"""O job que avisa lead e corretor do agendamento confirmado. TEC-170."""

import uuid
from datetime import UTC, datetime
from typing import Any

from mobia.domain.agendamento.confirmacao import avisar_confirmacao as _avisar_confirmacao


async def avisar_confirmacao(ctx: dict[str, Any], agendamento_id: str) -> str:
    """Os tres avisos do agendamento. O nome da funcao e `AVISAR_CONFIRMACAO_JOB`.

    O ARQ registra o job pelo `__name__` da funcao, entao o nome aqui e o
    contrato com `AgendadorDeAvisosArq` -- mudar um sem o outro faz o
    enfileiramento cair num job que nao existe. As portas vem do `ctx`: e o
    `startup` que decide a implementacao, e o teste troca sem tocar no job.
    """
    await _avisar_confirmacao(
        ctx["session_factory"],
        agendamento_id=uuid.UUID(agendamento_id),
        outbound=ctx["outbound"],
        email=ctx["email_ao_corretor"],
        calendario=ctx["calendario"],
        agora=datetime.now(UTC),
    )
    return "avisado"
