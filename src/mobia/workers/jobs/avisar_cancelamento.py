"""O job que avisa o corretor do agendamento cancelado. TEC-372, RN-12.3."""

import uuid
from datetime import UTC, datetime
from typing import Any

from mobia.domain.agendamento.cancelamento import avisar_cancelamento as _avisar_cancelamento


async def avisar_cancelamento(ctx: dict[str, Any], agendamento_id: str) -> str:
    """O e-mail ao corretor. O nome da funcao e `AVISAR_CANCELAMENTO_JOB`.

    Molde de `avisar_confirmacao`, e o mesmo contrato: o ARQ registra o job
    pelo `__name__`, entao o nome aqui e o que `AgendadorDeAvisosArq`
    enfileira -- mudar um sem o outro cai num job que nao existe. A porta de
    e-mail vem do `ctx`, e e a MESMA instancia que o aviso de confirmacao usa
    (`ctx["email_ao_corretor"]`).
    """
    await _avisar_cancelamento(
        ctx["session_factory"],
        agendamento_id=uuid.UUID(agendamento_id),
        email=ctx["email_ao_corretor"],
        agora=datetime.now(UTC),
    )
    return "avisado"
